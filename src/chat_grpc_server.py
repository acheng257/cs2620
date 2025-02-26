import argparse
import logging
import queue
import threading
import time
from concurrent import futures
from typing import Any, Dict

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

import src.protocols.grpc.chat_pb2 as chat_pb2
import src.protocols.grpc.chat_pb2_grpc as chat_pb2_grpc
from src.database.db_manager import DatabaseManager


class ChatServer(chat_pb2_grpc.ChatServerServicer):
    """gRPC server implementation for the chat service.

    This class implements all the RPC methods defined in the chat.proto service definition.
    It handles user authentication, message delivery, and account management operations.

    Attributes:
        db (DatabaseManager): Database manager instance for persistent storage
        active_subscribers (Dict[str, queue.Queue]): Maps usernames to their message queues
        lock (threading.Lock): Thread synchronization lock for subscriber management
    """

    def __init__(self, db_path: str = "chat.db") -> None:
        """Initialize the chat service.

        Args:
            db_path (str, optional): Path to the SQLite database file. Defaults to "chat.db".
        """
        self.db: DatabaseManager = DatabaseManager(db_path)
        # Maintain a mapping of logged-in users to a Queue for pushing messages.
        self.active_subscribers: Dict[str, queue.Queue] = {}  # {username: queue.Queue}
        self.lock: threading.Lock = threading.Lock()

    def CreateAccount(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        req_size = request.ByteSize()
        logging.info(f"CreateAccount: Received message of type {request.type} with size {req_size} bytes")
        
        # Extract username and password from the Struct payload.
        payload = MessageToDict(request.payload)
        username = payload.get("username")
        password = payload.get("password")
        if not username or not password:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Username and password required.")
            response = chat_pb2.ChatMessage()
            logging.info("CreateAccount: Sending empty response due to invalid arguments")
            return response

        if self.db.create_account(username, password):
            response_payload = {"text": "Account created successfully."}
            response = chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=username,
                timestamp=time.time(),
            )
        else:
            # Instead of setting an error, instruct the client to login.
            response_payload = {"text": "Username already exists. Please login instead."}
            response = chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=username,
                timestamp=time.time(),
            )
        
        res_size = response.ByteSize()
        logging.info(f"CreateAccount: Sending response of type {response.type} with size {res_size} bytes")
        return response

    def Login(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        req_size = request.ByteSize()
        logging.info(f"Login: Received message of type {request.type} with size {req_size} bytes")
        
        payload = MessageToDict(request.payload)
        username = payload.get("username")
        password = payload.get("password")
        if not username or not password:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Username and password required.")
            response = chat_pb2.ChatMessage()
            logging.info("Login: Sending empty response due to invalid arguments")
            return response

        # Handle dummy login for account existence check.
        if password == "dummy_password":
            if not self.db.user_exists(username):
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("Account does not exist.")
                response = chat_pb2.ChatMessage()
                logging.info("Login: Sending empty response because account does not exist")
                return response
            else:
                context.set_code(grpc.StatusCode.UNAUTHENTICATED)
                context.set_details("Invalid password.")
                response = chat_pb2.ChatMessage()
                logging.info("Login: Sending empty response due to invalid password in dummy login")
                return response

        if self.db.verify_login(username, password):
            unread_count = self.db.get_unread_message_count(username)
            response_payload = {
                "text": f"Login successful. You have {unread_count} unread messages."
            }
            response = chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=username,
                timestamp=time.time(),
            )
        else:
            context.set_code(grpc.StatusCode.UNAUTHENTICATED)
            context.set_details("Invalid username or password.")
            response = chat_pb2.ChatMessage()
        
        res_size = response.ByteSize()
        logging.info(f"Login: Sending response of type {response.type} with size {res_size} bytes")
        return response

    def SendMessage(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        req_size = request.ByteSize()
        logging.info(f"SendMessage: Received message of type {request.type} with size {req_size} bytes")
        
        payload = MessageToDict(request.payload)
        sender = request.sender
        recipient = request.recipient
        message_text = payload.get("text", "")
        if not self.db.user_exists(recipient):
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Recipient does not exist.")
            response = chat_pb2.ChatMessage()
            logging.info("SendMessage: Sending empty response because recipient does not exist")
            return response

        delivered = False
        with self.lock:
            if recipient in self.active_subscribers:
                delivered = True
                new_msg = chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.SEND_MESSAGE,
                    payload=request.payload,
                    sender=sender,
                    recipient=recipient,
                    timestamp=time.time(),
                )
                self.active_subscribers[recipient].put(new_msg)

        # Store the message in the database. Mark as delivered if we pushed it immediately.
        message_id = self.db.store_message(sender, recipient, message_text, delivered)
        if delivered and message_id:
            self.db.mark_message_as_delivered(message_id)

        response_payload = {"text": "Message sent successfully."}
        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=sender,
            timestamp=time.time(),
        )
        res_size = response.ByteSize()
        logging.info(f"SendMessage: Sending response of type {response.type} with size {res_size} bytes")
        return response

    def ReadMessages(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> Any:  # Using Any because it yields chat_pb2.ChatMessage
        req_size = request.ByteSize()
        logging.info(f"ReadMessages: Received streaming request from user {request.recipient} with size {req_size} bytes")
        
        # Client should provide its username in the 'recipient' field.
        username = request.recipient
        q: queue.Queue[chat_pb2.ChatMessage] = queue.Queue()
        with self.lock:
            self.active_subscribers[username] = q

        try:
            # Deliver any undelivered messages from the database.
            undelivered = self.db.get_undelivered_messages(username)
            for msg in undelivered:
                timestamp_val = msg.get("timestamp", time.time())
                try:
                    timestamp_val = float(timestamp_val)
                except (ValueError, TypeError):
                    timestamp_val = time.time()
                response_payload = {"text": msg["content"], "id": msg["id"]}
                chat_msg = chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.SEND_MESSAGE,
                    payload=ParseDict(response_payload, Struct()),
                    sender=msg["from"],
                    recipient=username,
                    timestamp=timestamp_val,
                )
                msg_size = chat_msg.ByteSize()
                logging.info(f"ReadMessages: Yielding undelivered message from {msg['from']} with size {msg_size} bytes")
                yield chat_msg
                self.db.mark_message_as_delivered(msg["id"])

            # Continuously process new messages as they arrive.
            while True:
                try:
                    message = q.get(timeout=60)
                    msg_size = message.ByteSize()
                    logging.info(f"ReadMessages: Yielding new message of type {message.type} with size {msg_size} bytes")
                    yield message
                except queue.Empty:
                    if context.is_active():
                        continue
                    else:
                        break
        finally:
            with self.lock:
                if username in self.active_subscribers:
                    del self.active_subscribers[username]

    def ListAccounts(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        req_size = request.ByteSize()
        logging.info(f"ListAccounts: Received message of type {request.type} with size {req_size} bytes")
        
        payload = MessageToDict(request.payload)
        pattern = payload.get("pattern", "")
        page = int(payload.get("page", 1))
        per_page = 10  # Number of accounts per page.
        result = self.db.list_accounts(pattern, page, per_page)
        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(result, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )
        res_size = response.ByteSize()
        logging.info(f"ListAccounts: Sending response of type {response.type} with size {res_size} bytes")
        return response

    def DeleteMessages(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        req_size = request.ByteSize()
        logging.info(f"DeleteMessages: Received message of type {request.type} with size {req_size} bytes")
        
        payload = MessageToDict(request.payload)
        message_ids = payload.get("message_ids", [])
        if not isinstance(message_ids, list):
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("'message_ids' must be a list.")
            response = chat_pb2.ChatMessage()
            logging.info("DeleteMessages: Sending empty response due to invalid message_ids format")
            return response

        success = self.db.delete_messages(request.sender, message_ids)
        if success:
            response_payload = {"text": "Messages deleted successfully."}
            msg_type = chat_pb2.MessageType.SUCCESS
        else:
            response_payload = {"text": "Failed to delete messages."}
            msg_type = chat_pb2.MessageType.ERROR

        response = chat_pb2.ChatMessage(
            type=msg_type,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )
        res_size = response.ByteSize()
        logging.info(f"DeleteMessages: Sending response of type {response.type} with size {res_size} bytes")
        return response

    def DeleteAccount(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        req_size = request.ByteSize()
        logging.info(f"DeleteAccount: Received message of type {request.type} with size {req_size} bytes")
        
        username = request.sender
        if self.db.delete_account(username):
            response_payload = {"text": "Account deleted successfully."}
            response = chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=username,
                timestamp=time.time(),
            )
        else:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Failed to delete account.")
            response = chat_pb2.ChatMessage()
        
        res_size = response.ByteSize()
        logging.info(f"DeleteAccount: Sending response of type {response.type} with size {res_size} bytes")
        return response

    def ListChatPartners(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        req_size = request.ByteSize()
        logging.info(f"ListChatPartners: Received message of type {request.type} with size {req_size} bytes")
        
        username = request.sender
        partners = self.db.get_chat_partners(username)
        unread_map = {}
        for p in partners:
            unread_map[p] = self.db.get_unread_between_users(username, p)
        response_payload = {"chat_partners": partners, "unread_map": unread_map}
        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )
        res_size = response.ByteSize()
        logging.info(f"ListChatPartners: Sending response of type {response.type} with size {res_size} bytes")
        return response

    def ReadConversation(self, request, context):
        req_size = request.ByteSize()
        logging.info(f"ReadConversation: Received message of type {request.type} with size {req_size} bytes")
        
        payload = MessageToDict(request.payload)
        partner = payload.get("partner")
        offset = int(payload.get("offset", 0))
        limit = int(payload.get("limit", 50))
        username = request.sender

        conversation = self.db.get_messages_between_users(username, partner, offset, limit)
        response_payload = {
            "messages": conversation.get("messages", []),
            "total": conversation.get("total", 0),
        }

        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )
        res_size = response.ByteSize()
        logging.info(f"ReadConversation: Sending response of type {response.type} with size {res_size} bytes")
        return response


def serve(host: str, port: int) -> None:
    """Start the gRPC server on a specified host and port."""
    print(f"Starting gRPC server on {host}:{port}...")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServerServicer_to_server(ChatServer(), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the gRPC Chat Server")
    parser.add_argument(
        "--host", type=str, default="[::]", help="Host to bind the gRPC server on (default: [::])"
    )
    parser.add_argument(
        "--port", type=int, default=50051, help="Port to bind the gRPC server on (default: 50051)"
    )
    args = parser.parse_args()

    # logging.basicConfig(level=logging.INFO)
    logging.basicConfig(
        filename="grpc_protocol_performance.log",
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    serve(args.host, args.port)
