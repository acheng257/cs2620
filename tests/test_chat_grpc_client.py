import time
import unittest

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

from src.chat_grpc_client import ChatClient
from src.protocols.grpc import chat_pb2, chat_pb2_grpc


class FakeChatServerStub:
    """
    A fake stub that simulates server responses for all RPCs.
    """

    def CreateAccount(self, request):
        payload = MessageToDict(request.payload)
        if payload.get("username") == "fail":
            response_payload = {"text": "Account creation failed."}
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=request.sender,
                timestamp=time.time(),
            )
        response_payload = {"text": "Account created successfully."}
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )

    def Login(self, request):
        payload = MessageToDict(request.payload)
        password = payload.get("password")
        if password == "pass":
            response_payload = {"text": "Login successful. You have 0 unread messages."}
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=request.sender,
                timestamp=time.time(),
            )
        else:
            response_payload = {"text": "Login failed."}
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=request.sender,
                timestamp=time.time(),
            )

    def SendMessage(self, request):
        if request.recipient == "nonexistent":
            response_payload = {"text": "Recipient does not exist."}
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=request.sender,
                timestamp=time.time(),
            )
        response_payload = {"text": "Message sent successfully."}
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )

    def ReadMessages(self, request):
        # Yield a single message for testing.
        yield chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SEND_MESSAGE,
            payload=ParseDict({"text": "Hello from server."}, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )

    def ListAccounts(self, request):
        response_payload = {"accounts": ["user1", "user2"], "page": 1, "per_page": 10}
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )

    def DeleteMessages(self, request):
        response_payload = {"text": "Messages deleted successfully."}
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )

    def DeleteAccount(self, request):
        response_payload = {"text": "Account deleted successfully."}
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )

    def ListChatPartners(self, request):
        response_payload = {"chat_partners": ["user2"], "unread_map": {"user2": 1}}
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )

    def ReadConversation(self, request):
        response_payload = {"messages": [{"text": "Hi", "id": 1}], "total": 1}
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )


class FakeChannel:
    def close(self):
        pass


def fake_channel_ready_future(channel):
    class FakeFuture:
        def result(self, timeout):
            return True

    return FakeFuture()


class TestChatClient(unittest.TestCase):
    def setUp(self):
        self._old_channel_ready_future = grpc.channel_ready_future
        grpc.channel_ready_future = fake_channel_ready_future

        self.client = ChatClient(username="testuser", host="127.0.0.1", port=50051)
        self.client.stub = FakeChatServerStub()
        self.client.channel = FakeChannel()

    def tearDown(self):
        grpc.channel_ready_future = self._old_channel_ready_future

    def test_connect(self):
        # For this test, override grpc.insecure_channel to return a FakeChannelWithUnary,
        # and override the ChatServerStub constructor to return our FakeChatServerStub.
        class FakeChannelWithUnary(FakeChannel):
            def unary_unary(self, method, request_serializer=None, response_deserializer=None, **kwargs):
                def dummy(request, timeout=None, metadata=None, credentials=None):
                    return None
                return dummy

        old_insecure_channel = grpc.insecure_channel
        grpc.insecure_channel = lambda target: FakeChannelWithUnary()
        old_stub_ctor = chat_pb2_grpc.ChatServerStub
        chat_pb2_grpc.ChatServerStub = lambda channel: FakeChatServerStub()

        connected = self.client.connect()

        # Restore the original functions.
        grpc.insecure_channel = old_insecure_channel
        chat_pb2_grpc.ChatServerStub = old_stub_ctor

        self.assertTrue(connected)

    def test_create_account(self):
        self.client.create_account("pass")
        success = self.client.create_account_sync("pass")
        self.assertTrue(success)

    def test_login_success(self):
        success = self.client.login("pass")
        self.assertTrue(success)
        success_sync, error = self.client.login_sync("pass")
        self.assertTrue(success_sync)
        self.assertIsNone(error)

    def test_login_fail(self):
        success = self.client.login("wrong")
        self.assertFalse(success)
        success_sync, error = self.client.login_sync("wrong")
        self.assertFalse(success_sync)
        self.assertIsNotNone(error)

    def test_send_message_success(self):
        result = self.client.send_message("user2", "Hello")
        self.assertTrue(result)
        result_sync = self.client.send_message_sync("user2", "Hello")
        self.assertEqual(result_sync.type, chat_pb2.MessageType.SUCCESS)

    def test_send_message_failure(self):
        result = self.client.send_message("nonexistent", "Hello")
        self.assertFalse(result)

    def test_read_messages(self):
        # Start the read thread and allow a short time for a message to be queued.
        self.client.start_read_thread()
        time.sleep(0.1)
        msg = self.client.incoming_messages_queue.get(timeout=1)
        self.assertEqual(msg.sender, "SERVER")
        self.assertEqual(MessageToDict(msg.payload).get("text"), "Hello from server.")

    def test_list_accounts(self):
        self.client.list_accounts("pattern", 1)
        response = self.client.list_accounts_sync("pattern", 1)
        result = MessageToDict(response.payload)
        self.assertIn("accounts", result)

    def test_delete_messages(self):
        self.client.delete_messages([1, 2])
        response = self.client.delete_messages_sync([1, 2])
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)

    def test_delete_account(self):
        self.client.delete_account()
        response = self.client.delete_account_sync()
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)

    def test_list_chat_partners(self):
        result = self.client.list_chat_partners()
        self.assertIn("chat_partners", result)
        response = self.client.list_chat_partners_sync()
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)

    def test_read_conversation(self):
        messages = self.client.read_conversation("user2", 0, 10)
        self.assertIsInstance(messages, list)
        response = self.client.read_conversation_sync("user2", 0, 10)
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)

    def test_close(self):
        self.client.close()
        self.assertFalse(self.client.running)


if __name__ == "__main__":
    unittest.main()
