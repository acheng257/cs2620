import logging
import time
import grpc
import queue
import threading
from concurrent import futures
from google.protobuf.json_format import MessageToDict, ParseDict

import chat_pb2
import chat_pb2_grpc
from src.database.db_manager import DatabaseManager

class ChatServiceServicer(chat_pb2_grpc.ChatServiceServicer):
    def __init__(self, db_path="chat.db"):
        self.db = DatabaseManager(db_path)
        # Maintain a mapping of logged-in users to a Queue for pushing messages.
        self.active_subscribers = {}  # {username: queue.Queue}
        self.lock = threading.Lock()

    def CreateAccount(self, request, context):
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
                payload=ParseDict(response_payload, chat_pb2.Struct()),
                sender="SERVER",
                recipient=username,
                timestamp=time.time()
            )
            return response
        else:
            context.set_code(grpc.StatusCode.ALREADY_EXISTS)
            context.set_details("Username already exists.")
            return chat_pb2.ChatMessage()

    def Login(self, request, context):
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
                payload=ParseDict(response_payload, chat_pb2.Struct()),
                sender="SERVER",
                recipient=username,
                timestamp=time.time()
            )
            return response
        else:
            context.set_code(grpc.StatusCode.UNAUTHENTICATED)
            context.set_details("Invalid username or password.")
            return chat_pb2.ChatMessage()

    def SendMessage(self, request, context):
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
                    timestamp=time.time()
                )
                self.active_subscribers[recipient].put(new_msg)

        # Store the message in the database. Mark as delivered if we pushed it immediately.
        message_id = self.db.store_message(sender, recipient, message_text, delivered)
        if delivered:
            self.db.mark_message_as_delivered(message_id)

        response_payload = {"text": "Message sent successfully."}
        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, chat_pb2.Struct()),
            sender="SERVER",
            recipient=sender,
            timestamp=time.time()
        )
        return response

    def ReadMessages(self, request, context):
        # Client should provide its username in the 'recipient' field.
        username = request.recipient
        # Register subscriber by creating a new Queue for this user.
        q = queue.Queue()
        with self.lock:
            self.active_subscribers[username] = q

        try:
            # Deliver any undelivered messages from the database.
            undelivered = self.db.get_undelivered_messages(username)
            for msg in undelivered:
                response_payload = {"text": msg["content"], "id": msg["id"]}
                chat_msg = chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.SEND_MESSAGE,
                    payload=ParseDict(response_payload, chat_pb2.Struct()),
                    sender=msg["from"],
                    recipient=username,
                    timestamp=msg.get("timestamp", time.time())
                )
                yield chat_msg
                self.db.mark_message_as_delivered(msg["id"])

            # Continuously process new messages as they arrive.
            while True:
                try:
                    # Wait up to 60 seconds for a new message.
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

    def ListAccounts(self, request, context):
        payload = MessageToDict(request.payload)
        pattern = payload.get("pattern", "")
        page = int(payload.get("page", 1))
        per_page = 10  # Number of accounts per page.
        result = self.db.list_accounts(pattern, page, per_page)
        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(result, chat_pb2.Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time()
        )
        return response

    def DeleteMessages(self, request, context):
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
            payload=ParseDict(response_payload, chat_pb2.Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time()
        )
        return response

    def DeleteAccount(self, request, context):
        username = request.sender
        if self.db.delete_account(username):
            response_payload = {"text": "Account deleted successfully."}
            response = chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                payload=ParseDict(response_payload, chat_pb2.Struct()),
                sender="SERVER",
                recipient=username,
                timestamp=time.time()
            )
            return response
        else:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Failed to delete account.")
            return chat_pb2.ChatMessage()

    def ListChatPartners(self, request, context):
        username = request.sender
        partners = self.db.get_chat_partners(username)
        unread_map = {}
        for p in partners:
            unread_map[p] = self.db.get_unread_between_users(username, p)
        response_payload = {"chat_partners": partners, "unread_map": unread_map}
        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, chat_pb2.Struct()),
            sender="SERVER",
            recipient=username,
            timestamp=time.time()
        )
        return response

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServiceServicer(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    logging.basicConfig()
    serve()
