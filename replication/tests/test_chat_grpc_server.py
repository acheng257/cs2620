import queue
import time
import unittest
import logging
import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

from src.chat_grpc_server import ChatServer
from src.protocols.grpc import chat_pb2
from src.replication.replication_manager import ServerRole

# Ensure each log record gets a default 'server_info' to avoid KeyError in our custom formatter.
from src.replication.replication_manager import replication_logger

for handler in replication_logger.handlers:
    handler.addFilter(
        lambda record: setattr(record, "server_info", getattr(record, "server_info", "N/A")) or True
    )


class FakeDatabaseManager:
    """
    A fake in-memory database manager to simulate account and message storage.
    """

    def __init__(self):
        self.accounts = {}  # username -> password
        self.messages = {}  # message_id -> message dict
        self.message_counter = 1
        self.undelivered = {}  # username -> list of message dicts

    def create_account(self, username, password):
        if username in self.accounts:
            return False
        self.accounts[username] = password
        return True

    def user_exists(self, username):
        return username in self.accounts

    def verify_login(self, username, password):
        # For testing purposes, we could check the password.
        return self.accounts.get(username) == password

    def get_unread_message_count(self, username):
        return len(self.undelivered.get(username, []))

    def store_message(self, sender, recipient, content, is_delivered=True, forced_id=None):
        message_id = forced_id if forced_id is not None else self.message_counter
        if forced_id is None:
            self.message_counter += 1
        msg = {
            "id": message_id,
            "from": sender,
            "to": recipient,
            "content": content,
            "timestamp": time.time(),
            "is_read": False,
            "is_delivered": is_delivered,
        }
        self.messages[message_id] = msg
        if not is_delivered:
            self.undelivered.setdefault(recipient, []).append(msg)
        return message_id

    def mark_message_as_delivered(self, message_id):
        if message_id in self.messages:
            self.messages[message_id]["is_delivered"] = True
            recipient = self.messages[message_id]["to"]
            if recipient in self.undelivered:
                self.undelivered[recipient] = [
                    m for m in self.undelivered[recipient] if m["id"] != message_id
                ]

    def get_undelivered_messages(self, username):
        return self.undelivered.get(username, [])

    def list_accounts(self, pattern, page, per_page):
        users = list(self.accounts.keys())
        return {"users": users, "total": len(users), "page": page, "per_page": per_page}

    def delete_messages(self, username, message_ids):
        success = True
        for mid in message_ids:
            if mid in self.messages:
                del self.messages[mid]
            else:
                success = False
        return success

    def delete_account(self, username):
        if username in self.accounts:
            del self.accounts[username]
            return True
        return False

    def get_chat_partners(self, username):
        partners = set()
        for msg in self.messages.values():
            if msg["from"] == username:
                partners.add(msg["to"])
            elif msg["to"] == username:
                partners.add(msg["from"])
        return list(partners)

    def get_unread_between_users(self, username, partner):
        count = 0
        for msg in self.get_undelivered_messages(username):
            if msg["from"] == partner:
                count += 1
        return count

    def get_messages_between_users(self, username, partner, offset=0, limit=999999):
        conversation = [
            msg
            for msg in self.messages.values()
            if (msg["from"] == username and msg["to"] == partner)
            or (msg["from"] == partner and msg["to"] == username)
        ]
        conversation.sort(key=lambda m: m["timestamp"], reverse=True)
        total = len(conversation)
        return {"messages": conversation[offset : offset + limit], "total": total}


class FakeContext:
    """
    A fake gRPC ServicerContext to capture status codes and details.
    """

    def __init__(self):
        self.code = None
        self.details_text = None

    def set_code(self, code):
        self.code = code

    def set_details(self, details):
        self.details_text = details

    def is_active(self):
        return True


class TestChatServer(unittest.TestCase):
    def setUp(self):
        # Create a ChatServer instance.
        self.server = ChatServer()
        # Replace the real database manager with our fake one.
        self.server.db = FakeDatabaseManager()
        # Make sure the active users dictionary is initialized.
        self.server.active_users = {}
        # Force the server to behave as the leader.
        self.server.replication_manager.role = ServerRole.LEADER
        self.server.replication_manager.replicate_account = lambda username: True
        self.server.replication_manager.replicate_message = (
            lambda message_id, sender, recipient, content: True
        )
        self.server.replication_manager.replicate_operation = lambda request: True
        self.context = FakeContext()

    def test_create_account_success(self):
        payload = {"username": "user1", "password": "pass"}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.CREATE_ACCOUNT,
            payload=ParseDict(payload, Struct()),
            sender="user1",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.CreateAccount(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)
        text = MessageToDict(response.payload).get("text", "")
        self.assertIn("Account created successfully", text)

    def test_create_account_already_exists(self):
        payload = {"username": "user1", "password": "pass"}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.CREATE_ACCOUNT,
            payload=ParseDict(payload, Struct()),
            sender="user1",
            recipient="SERVER",
            timestamp=time.time(),
        )
        _ = self.server.CreateAccount(request, self.context)
        response = self.server.CreateAccount(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.ERROR)
        text = MessageToDict(response.payload).get("text", "")
        self.assertIn("Username already exists", text)

    def test_login_not_found(self):
        payload = {"username": "user2", "password": "dummy"}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LOGIN,
            payload=ParseDict(payload, Struct()),
            sender="user2",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.Login(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.ERROR)
        text = MessageToDict(response.payload).get("text", "")
        self.assertIn("User does not exist", text)

    def test_login_success(self):
        # Since Login only checks existence, create the account first.
        self.server.db.create_account("user1", "pass")
        payload = {"username": "user1", "password": "any"}  # password is not verified
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LOGIN,
            payload=ParseDict(payload, Struct()),
            sender="user1",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.Login(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)
        text = MessageToDict(response.payload).get("text", "")
        self.assertIn("Login successful", text)

    def test_send_message_success(self):
        self.server.db.create_account("sender", "pass")
        self.server.db.create_account("recipient", "pass")
        # Set up an active user queue for "recipient" in active_users.
        q = queue.Queue()
        self.server.active_users["recipient"] = {q}
        payload = {"text": "Hello"}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SEND_MESSAGE,
            payload=ParseDict(payload, Struct()),
            sender="sender",
            recipient="recipient",
            timestamp=time.time(),
        )
        response = self.server.SendMessage(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)
        text = MessageToDict(response.payload).get("text", "")
        self.assertIn("Message sent successfully", text)
        # Verify that the message was delivered to the recipient's queue.
        delivered_msg = q.get(timeout=1)
        self.assertEqual(delivered_msg.sender, "sender")
        payload_text = MessageToDict(delivered_msg.payload).get("text", "")
        self.assertEqual(payload_text, "Hello")

    def test_send_message_recipient_not_found(self):
        self.server.db.create_account("sender", "pass")
        payload = {"text": "Hello"}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SEND_MESSAGE,
            payload=ParseDict(payload, Struct()),
            sender="sender",
            recipient="nonexistent",
            timestamp=time.time(),
        )
        response = self.server.SendMessage(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.ERROR)
        text = MessageToDict(response.payload).get("text", "")
        self.assertIn("Recipient does not exist", text)

    def test_list_accounts(self):
        self.server.db.create_account("user1", "pass")
        self.server.db.create_account("user2", "pass")
        payload = {"pattern": "", "page": 1}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LIST_ACCOUNTS,
            payload=ParseDict(payload, Struct()),
            sender="user1",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.ListAccounts(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)
        result = MessageToDict(response.payload)
        self.assertIn("users", result)
        self.assertEqual(result.get("page"), 1)

    def test_delete_messages_success(self):
        self.server.db.create_account("user1", "pass")
        msg_id = self.server.db.store_message("user1", "user1", "Test", True)
        payload = {"message_ids": [msg_id]}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.DELETE_MESSAGES,
            payload=ParseDict(payload, Struct()),
            sender="user1",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.DeleteMessages(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)
        text = MessageToDict(response.payload).get("text", "")
        self.assertIn("deleted successfully", text)

    def test_delete_messages_invalid(self):
        payload = {"message_ids": "not a list"}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.DELETE_MESSAGES,
            payload=ParseDict(payload, Struct()),
            sender="user1",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.DeleteMessages(request, self.context)
        # Expect the context code to be set to INVALID_ARGUMENT.
        self.assertEqual(self.context.code, grpc.StatusCode.INVALID_ARGUMENT)

    def test_delete_account_success(self):
        self.server.db.create_account("user1", "pass")
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.DELETE_ACCOUNT,
            payload=Struct(),
            sender="user1",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.DeleteAccount(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)

    def test_delete_account_failure(self):
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.DELETE_ACCOUNT,
            payload=Struct(),
            sender="nonexistent",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.DeleteAccount(request, self.context)
        self.assertEqual(self.context.code, grpc.StatusCode.INTERNAL)

    def test_list_chat_partners(self):
        self.server.db.create_account("user1", "pass")
        self.server.db.create_account("user2", "pass")
        self.server.db.store_message("user1", "user2", "Hi", True)
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LIST_CHAT_PARTNERS,
            payload=Struct(),
            sender="user1",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.ListChatPartners(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)
        result = MessageToDict(response.payload)
        self.assertIn("chat_partners", result)
        self.assertIn("unread_map", result)

    def test_read_conversation(self):
        self.server.db.create_account("user1", "pass")
        self.server.db.create_account("user2", "pass")
        self.server.db.store_message("user1", "user2", "Hello", True)
        self.server.db.store_message("user2", "user1", "Hi", True)
        payload = {"partner": "user2", "offset": 0, "limit": 10}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.READ_MESSAGES,
            payload=ParseDict(payload, Struct()),
            sender="user1",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.ReadConversation(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)
        result = MessageToDict(response.payload)
        self.assertIn("messages", result)
        self.assertIn("total", result)


if __name__ == "__main__":
    unittest.main()
