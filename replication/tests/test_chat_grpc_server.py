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
        # For testing purposes, check the password.
        return self.accounts.get(username) == password

    def verify_password(self, username, password):
        # Added so that ChatServer.Login can verify credentials.
        return self.accounts.get(username) == password

    def get_unread_message_count(self, username):
        return len(self.undelivered.get(username, []))

    def store_message(self, sender, recipient, content, is_delivered=True, forced_id=None):
        message_id = forced_id if forced_id is not None else self.message_counter
        if forced_id is None:
            self.message_counter += 1
        msg = {
            "id": message_id,
            "sender": sender,
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
            if msg["sender"] == username:
                partners.add(msg["to"])
            elif msg["to"] == username:
                partners.add(msg["sender"])
        return list(partners)

    def get_unread_between_users(self, username, partner):
        count = 0
        for msg in self.get_undelivered_messages(username):
            if msg["sender"] == partner:
                count += 1
        return count

    def get_messages_between_users(self, username, partner, offset=0, limit=999999):
        conversation = [
            msg
            for msg in self.messages.values()
            if (msg["sender"] == username and msg["to"] == partner)
            or (msg["sender"] == partner and msg["to"] == username)
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
        # Create the account with the intended password.
        self.server.db.create_account("user1", "pass")
        payload = {"username": "user1", "password": "pass"}
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

    def test_login_dummy_nonexistent(self):
        # Login with dummy password for a non-existent account should return NOT_FOUND.
        payload = {"username": "dummy_user", "password": "dummy_password"}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LOGIN,
            payload=ParseDict(payload, Struct()),
            sender="dummy_user",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.Login(request, self.context)
        self.assertEqual(self.context.code, grpc.StatusCode.NOT_FOUND)
        self.context.code = None

    def test_login_dummy_existing(self):
        # Login with dummy password for an existing account should return UNAUTHENTICATED.
        self.server.db.create_account("dummy_user", "somepass")
        payload = {"username": "dummy_user", "password": "dummy_password"}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LOGIN,
            payload=ParseDict(payload, Struct()),
            sender="dummy_user",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.Login(request, self.context)
        self.assertEqual(self.context.code, grpc.StatusCode.UNAUTHENTICATED)
        self.context.code = None

    def test_login_invalid_credentials(self):
        # When login credentials are invalid, the server should respond with UNAUTHENTICATED.
        self.server.db.create_account("user_invalid", "pass")
        payload = {"username": "user_invalid", "password": "wrong"}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LOGIN,
            payload=ParseDict(payload, Struct()),
            sender="user_invalid",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.Login(request, self.context)
        self.assertEqual(self.context.code, grpc.StatusCode.UNAUTHENTICATED)
        self.context.code = None

    def test_send_message_success(self):
        self.server.db.create_account("sender", "pass")
        self.server.db.create_account("recipient", "pass")
        # Set up an active user queue for "recipient" in active_users using a list.
        q = queue.Queue()
        self.server.active_users["recipient"] = [q]
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
        _ = self.server.DeleteMessages(request, self.context)
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
        # Test listing chat partners for a user.
        self.server.db.create_account("user1", "pass")
        self.server.db.create_account("user2", "pass")
        self.server.db.store_message("user1", "user2", "Hello", True)
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
        # Test reading a conversation between two users.
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

    def test_create_account_missing_username(self):
        # Missing username should trigger INVALID_ARGUMENT.
        payload = {"password": "pass"}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.CREATE_ACCOUNT,
            payload=ParseDict(payload, Struct()),
            sender="",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.CreateAccount(request, self.context)
        # When required fields are missing, the server returns an empty ChatMessage
        # and sets the context status.
        self.assertEqual(self.context.code, grpc.StatusCode.INVALID_ARGUMENT)
        self.context.code = None

    def test_create_account_missing_password(self):
        # Missing password should trigger INVALID_ARGUMENT.
        payload = {"username": "user_missing_pass"}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.CREATE_ACCOUNT,
            payload=ParseDict(payload, Struct()),
            sender="user_missing_pass",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.CreateAccount(request, self.context)
        self.assertEqual(self.context.code, grpc.StatusCode.INVALID_ARGUMENT)
        self.context.code = None

    def test_send_message_not_delivered(self):
        # Test SendMessage when recipient is not subscribed, so the message remains undelivered.
        self.server.db.create_account("sender", "pass")
        self.server.db.create_account("recipient", "pass")
        # Ensure recipient does not have an active subscriber.
        if "recipient" in self.server.active_users:
            del self.server.active_users["recipient"]

        payload = {"text": "Hello no delivery"}
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SEND_MESSAGE,
            payload=ParseDict(payload, Struct()),
            sender="sender",
            recipient="recipient",
            timestamp=time.time(),
        )
        response = self.server.SendMessage(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)
        # Check stored message: it should not be marked as delivered.
        stored = list(self.server.db.messages.values())[0]
        self.assertFalse(stored["is_delivered"])

    def test_read_messages_undelivered_and_stream(self):
        # Test the ReadMessages RPC for both undelivered messages and streaming new messages.
        self.server.db.create_account("user1", "pass")
        # Pre-load an undelivered message.
        msg_id = self.server.db.store_message("sender", "user1", "Undelivered msg", False)
        # Create a request for reading messages.
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.READ_MESSAGES,
            payload=Struct(),
            sender="sender",
            recipient="user1",
            timestamp=time.time(),
        )
        # Call ReadMessages as a generator.
        gen = self.server.ReadMessages(request, self.context)
        # First yielded message should be the undelivered one.
        first_msg = next(gen)
        self.assertEqual(first_msg.type, chat_pb2.MessageType.SEND_MESSAGE)
        payload_dict = MessageToDict(first_msg.payload)
        self.assertEqual(payload_dict.get("text"), "Undelivered msg")
        # The message should be marked as delivered now.
        self.assertTrue(self.server.db.messages[msg_id]["is_delivered"])
        # Now simulate sending a new message.
        new_msg = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SEND_MESSAGE,
            payload=ParseDict({"text": "New streamed msg"}, Struct()),
            sender="streamer",
            recipient="user1",
            timestamp=time.time(),
        )
        # Get the subscriber queue created by ReadMessages.
        with self.server.lock:
            # Assuming there is only one subscriber, take the first queue.
            q = self.server.active_users["user1"][0]
        q.put(new_msg)
        # Next value from generator should be the new message.
        streamed = next(gen)
        self.assertEqual(MessageToDict(streamed.payload).get("text"), "New streamed msg")

        # Cleanup: cancel the generator by using a context that is not active.
        class InactiveContext(FakeContext):
            def is_active(self):
                return False

        gen = self.server.ReadMessages(request, InactiveContext())
        with self.assertRaises(StopIteration):
            next(gen)

    def test_mark_read_invalid_format(self):
        # Test marking messages as read with invalid message_ids format.
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SEND_MESSAGE,
            payload=ParseDict({"message_ids": "not_a_list"}, Struct()),
            sender="user1",
            recipient="SERVER",
            timestamp=time.time(),
        )
        _ = self.server.MarkRead(request, self.context)
        self.assertEqual(self.context.code, grpc.StatusCode.INVALID_ARGUMENT)

    def test_get_leader(self):
        # Test getting the current leader information.
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SEND_MESSAGE,
            payload=Struct(),
            sender="user1",
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.server.GetLeader(request, self.context)
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)
        payload_dict = MessageToDict(response.payload)
        self.assertIn("leader", payload_dict)


if __name__ == "__main__":
    unittest.main()
