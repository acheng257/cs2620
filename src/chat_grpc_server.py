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
    """
    gRPC server implementation for the chat service.

    This class implements all the RPC methods defined in the chat.proto service definition.
    It handles user authentication, message delivery, and account management operations.
    """

    def __init__(self, db_path: str = "chat.db") -> None:
        self.db: DatabaseManager = DatabaseManager(db_path)
        # Maintain a mapping of logged-in users to a Queue for pushing messages.
        self.active_subscribers: Dict[str, queue.Queue] = {}  # {username: queue.Queue}
        self.lock: threading.Lock = threading.Lock()

    def CreateAccount(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
        # Deserialization timing for request payload.
        start_deser = time.perf_counter()
        payload = MessageToDict(request.payload)
        end_deser = time.perf_counter()
        print(f"[CreateAccount] Deserialization took {end_deser - start_deser:.6f} seconds")

        username = payload.get("username")
        password = payload.get("password")
        if not username or not password:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Username and password required.")
            return chat_pb2.ChatMessage()

        if self.db.create_account(username, password):
            response_payload = {"text": "Account created successfully."}
        else:
            response_payload = {"text": "Username already exists. Please login instead."}

        # Serialization timing for response payload.
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(response_payload, Struct())
        end_ser = time.perf_counter()
        print(f"[CreateAccount] Serialization took {end_ser - start_ser:.6f} seconds")
        
        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=parsed_payload,
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )
        return response

    def Login(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
        # Measure deserialization of request payload.
        start_deser = time.perf_counter()
        payload = MessageToDict(request.payload)
        end_deser = time.perf_counter()
        print(f"[Login] Deserialization took {end_deser - start_deser:.6f} seconds")

        username = payload.get("username")
        password = payload.get("password")
        if not username or not password:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Username and password required.")
            return chat_pb2.ChatMessage()

        # Handle dummy login for account existence check.
        if password == "dummy_password":
            if not self.db.user_exists(username):
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("Account does not exist.")
                return chat_pb2.ChatMessage()
            else:
                context.set_code(grpc.StatusCode.UNAUTHENTICATED)
                context.set_details("Invalid password.")
                return chat_pb2.ChatMessage()

        if self.db.verify_login(username, password):
            unread_count = self.db.get_unread_message_count(username)
            response_payload = {"text": f"Login successful. You have {unread_count} unread messages."}
        else:
            context.set_code(grpc.StatusCode.UNAUTHENTICATED)
            context.set_details("Invalid username or password.")
            return chat_pb2.ChatMessage()

        # Measure serialization of response payload.
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(response_payload, Struct())
        end_ser = time.perf_counter()
        print(f"[Login] Serialization took {end_ser - start_ser:.6f} seconds")
        
        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=parsed_payload,
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )
        return response

    def SendMessage(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
        start_deser = time.perf_counter()
        payload = MessageToDict(request.payload)
        end_deser = time.perf_counter()
        print(f"[SendMessage] Deserialization took {end_deser - start_deser:.6f} seconds")
        
        sender = request.sender
        recipient = request.recipient
        message_text = payload.get("text", "")
        if not self.db.user_exists(recipient):
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Recipient does not exist.")
            return chat_pb2.ChatMessage()

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

        message_id = self.db.store_message(sender, recipient, message_text, delivered)
        if delivered and message_id:
            self.db.mark_message_as_delivered(message_id)

        response_payload = {"text": "Message sent successfully."}
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(response_payload, Struct())
        end_ser = time.perf_counter()
        print(f"[SendMessage] Serialization took {end_ser - start_ser:.6f} seconds")
        
        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=parsed_payload,
            sender="SERVER",
            recipient=sender,
            timestamp=time.time(),
        )
        return response

    def ReadMessages(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext):
        username = request.recipient
        q: queue.Queue[chat_pb2.ChatMessage] = queue.Queue()
        with self.lock:
            self.active_subscribers[username] = q

        try:
            # Deliver undelivered messages.
            undelivered = self.db.get_undelivered_messages(username)
            for msg in undelivered:
                timestamp_val = msg.get("timestamp", time.time())
                try:
                    timestamp_val = float(timestamp_val)
                except (ValueError, TypeError):
                    timestamp_val = time.time()
                response_payload = {"text": msg["content"], "id": msg["id"]}
                start_ser = time.perf_counter()
                parsed_payload = ParseDict(response_payload, Struct())
                end_ser = time.perf_counter()
                print(f"[ReadMessages] Serialization (undelivered) took {end_ser - start_ser:.6f} seconds")
                
                chat_msg = chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.SEND_MESSAGE,
                    payload=parsed_payload,
                    sender=msg["from"],
                    recipient=username,
                    timestamp=timestamp_val,
                )
                yield chat_msg
                self.db.mark_message_as_delivered(msg["id"])

            # Continuously stream new messages.
            while True:
                try:
                    message = q.get(timeout=60)
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

    def ListAccounts(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
        start_deser = time.perf_counter()
        payload = MessageToDict(request.payload)
        end_deser = time.perf_counter()
        print(f"[ListAccounts] Deserialization took {end_deser - start_deser:.6f} seconds")
        
        pattern = payload.get("pattern", "")
        page = int(payload.get("page", 1))
        per_page = 10  # Number of accounts per page.
        result = self.db.list_accounts(pattern, page, per_page)
        
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(result, Struct())
        end_ser = time.perf_counter()
        print(f"[ListAccounts] Serialization took {end_ser - start_ser:.6f} seconds")
        
        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=parsed_payload,
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )
        return response

    def DeleteMessages(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
        start_deser = time.perf_counter()
        payload = MessageToDict(request.payload)
        end_deser = time.perf_counter()
        print(f"[DeleteMessages] Deserialization took {end_deser - start_deser:.6f} seconds")
        
        message_ids = payload.get("message_ids", [])
        if not isinstance(message_ids, list):
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("'message_ids' must be a list.")
            return chat_pb2.ChatMessage()

        success = self.db.delete_messages(request.sender, message_ids)
        if success:
            response_payload = {"text": "Messages deleted successfully."}
            msg_type = chat_pb2.MessageType.SUCCESS
        else:
            response_payload = {"text": "Failed to delete messages."}
            msg_type = chat_pb2.MessageType.ERROR

        start_ser = time.perf_counter()
        parsed_payload = ParseDict(response_payload, Struct())
        end_ser = time.perf_counter()
        print(f"[DeleteMessages] Serialization took {end_ser - start_ser:.6f} seconds")
        
        response = chat_pb2.ChatMessage(
            type=msg_type,
            payload=parsed_payload,
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )
        return response

    def DeleteAccount(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
        username = request.sender
        if self.db.delete_account(username):
            response_payload = {"text": "Account deleted successfully."}
            start_ser = time.perf_counter()
            parsed_payload = ParseDict(response_payload, Struct())
            end_ser = time.perf_counter()
            print(f"[DeleteAccount] Serialization took {end_ser - start_ser:.6f} seconds")
            response = chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                payload=parsed_payload,
                sender="SERVER",
                recipient=username,
                timestamp=time.time(),
            )
            return response
        else:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Failed to delete account.")
            return chat_pb2.ChatMessage()

    def ListChatPartners(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
        username = request.sender
        partners = self.db.get_chat_partners(username)
        unread_map = {}
        for p in partners:
            unread_map[p] = self.db.get_unread_between_users(username, p)
        response_payload = {"chat_partners": partners, "unread_map": unread_map}
        
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(response_payload, Struct())
        end_ser = time.perf_counter()
        print(f"[ListChatPartners] Serialization took {end_ser - start_ser:.6f} seconds")
        
        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=parsed_payload,
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )
        return response

    def ReadConversation(self, request, context):
        # Expect payload to include 'partner', 'offset', and 'limit'
        start_deser = time.perf_counter()
        payload = MessageToDict(request.payload)
        end_deser = time.perf_counter()
        print(f"[ReadConversation] Deserialization took {end_deser - start_deser:.6f} seconds")
        
        partner = payload.get("partner")
        offset = int(payload.get("offset", 0))
        limit = int(payload.get("limit", 50))
        username = request.sender

        conversation = self.db.get_messages_between_users(username, partner, offset, limit)
        response_payload = {
            "messages": conversation.get("messages", []),
            "total": conversation.get("total", 0),
        }

        start_ser = time.perf_counter()
        parsed_payload = ParseDict(response_payload, Struct())
        end_ser = time.perf_counter()
        print(f"[ReadConversation] Serialization took {end_ser - start_ser:.6f} seconds")
        
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=parsed_payload,
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )


def serve(host: str, port: int) -> None:
    print(f"Starting gRPC server on {host}:{port}...")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServerServicer_to_server(ChatServer(), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the gRPC Chat Server")
    parser.add_argument("--host", type=str, default="[::]", help="Host to bind the gRPC server on (default: [::])")
    parser.add_argument("--port", type=int, default=50051, help="Port to bind the gRPC server on (default: 50051)")
    args = parser.parse_args()

    logging.basicConfig()
    serve(args.host, args.port)
