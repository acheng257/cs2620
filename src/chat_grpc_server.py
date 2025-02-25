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
        """Create a new user account.

        Args:
            request (chat_pb2.ChatMessage): Contains username and password in payload
            context (grpc.ServicerContext): gRPC service context

        Returns:
            chat_pb2.ChatMessage: Success message if account created, error otherwise

        Sets error status codes:
            INVALID_ARGUMENT: If username or password is missing
            ALREADY_EXISTS: If username is already taken
        """
        # Extract username and password from the Struct payload.
        payload = MessageToDict(request.payload)
        username = payload.get("username")
        password = payload.get("password")
        if not username or not password:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Username and password required.")
            return chat_pb2.ChatMessage()

        if self.db.create_account(username, password):
            response_payload = {"text": "Account created successfully."}
            response = chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=username,
                timestamp=time.time(),
            )
            return response
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
            return response

    def Login(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """Authenticate a user and log them in.

        Args:
            request (chat_pb2.ChatMessage): Contains username and password in payload
            context (grpc.ServicerContext): gRPC service context

        Returns:
            chat_pb2.ChatMessage: Success message with unread count if login successful

        Sets error status codes:
            INVALID_ARGUMENT: If username or password is missing
            NOT_FOUND: If account doesn't exist (during dummy login)
            UNAUTHENTICATED: If password is incorrect
        """
        payload = MessageToDict(request.payload)
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
            return response
        else:
            context.set_code(grpc.StatusCode.UNAUTHENTICATED)
            context.set_details("Invalid username or password.")
            return chat_pb2.ChatMessage()

    def SendMessage(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """Send a message to another user.

        If the recipient is online (has an active subscriber), delivers the message
        immediately. Otherwise, stores it for later delivery.

        Args:
            request (chat_pb2.ChatMessage): Contains sender, recipient, and message text
            context (grpc.ServicerContext): gRPC service context

        Returns:
            chat_pb2.ChatMessage: Success confirmation message

        Sets error status codes:
            NOT_FOUND: If recipient doesn't exist
        """
        payload = MessageToDict(request.payload)
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
        return response

    def ReadMessages(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> Any:  # Using Any because it yields chat_pb2.ChatMessage
        """Stream messages to a client.

        Creates a message queue for the client and streams both undelivered messages
        from the database and new incoming messages. Maintains the connection until
        the client disconnects or a timeout occurs.

        Args:
            request (chat_pb2.ChatMessage): Contains recipient (username) for message delivery
            context (grpc.ServicerContext): gRPC service context

        Yields:
            chat_pb2.ChatMessage: Stream of messages for the client
        """
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
                yield chat_msg
                self.db.mark_message_as_delivered(msg["id"])

            # Continuously process new messages as they arrive.
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

    def ListAccounts(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """List user accounts matching a pattern.

        Args:
            request (chat_pb2.ChatMessage): Contains search pattern and page number
            context (grpc.ServicerContext): gRPC service context

        Returns:
            chat_pb2.ChatMessage: List of matching accounts with pagination info
        """
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
        return response

    def DeleteMessages(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """Delete specified messages for a user.

        Args:
            request (chat_pb2.ChatMessage): Contains list of message IDs to delete
            context (grpc.ServicerContext): gRPC service context

        Returns:
            chat_pb2.ChatMessage: Success or error message

        Sets error status codes:
            INVALID_ARGUMENT: If message_ids is not a list
        """
        payload = MessageToDict(request.payload)
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

        response = chat_pb2.ChatMessage(
            type=msg_type,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )
        return response

    def DeleteAccount(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """Delete a user's account.

        Args:
            request (chat_pb2.ChatMessage): Contains username in sender field
            context (grpc.ServicerContext): gRPC service context

        Returns:
            chat_pb2.ChatMessage: Success or error message

        Sets error status codes:
            INTERNAL: If account deletion fails
        """
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
            return response
        else:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Failed to delete account.")
            return chat_pb2.ChatMessage()

    def ListChatPartners(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """List all users that the requesting user has chatted with.

        Also includes the count of unread messages from each chat partner.

        Args:
            request (chat_pb2.ChatMessage): Contains username in sender field
            context (grpc.ServicerContext): gRPC service context

        Returns:
            chat_pb2.ChatMessage: List of chat partners and unread message counts
        """
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
        return response

    def ReadConversation(self, request, context):
        # Expect payload to include 'partner', 'offset', and 'limit'
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

        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )


def serve() -> None:
    """Start the gRPC server.

    Creates a gRPC server with max 10 worker threads and starts it on port 50051.
    The server runs indefinitely until terminated.
    """
    print("Starting gRPC server on port 50051...")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServerServicer_to_server(ChatServer(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig()
    serve()
