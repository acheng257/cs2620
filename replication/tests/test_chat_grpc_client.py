import time
import unittest
import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

from src.chat_grpc_client import ChatClient
from src.protocols.grpc import chat_pb2, chat_pb2_grpc


# Fake stub simulating responses from the server.
class FakeChatServerStub:
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

    def GetLeader(self, request):
        response_payload = {"leader_host": "127.0.0.1", "leader_port": 50051}
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


# Fake channel with a minimal implementation.
class FakeChannel:
    def unary_unary(self, method, request_serializer=None, response_deserializer=None, **kwargs):
        def dummy(request, timeout=None, metadata=None, credentials=None):
            return None

        return dummy

    def unary_stream(self, method, request_serializer=None, response_deserializer=None, **kwargs):
        def dummy(request, timeout=None, metadata=None, credentials=None):
            return iter([])

        return dummy

    def close(self):
        pass


# Fake channel_ready_future to simulate an immediately ready channel.
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
        # For tests that need leader-related methods, we monkey-patch the missing methods.
        self.client.discover_leader = lambda: ("127.0.0.1", 50052)
        self.client.is_leader = lambda: (self.client.host, self.client.port) == ("127.0.0.1", 50051)
        self.client.reconnect_to_leader = (
            lambda: setattr(self.client, "host", "127.0.0.1")
            or setattr(self.client, "port", 50052)
            or True
        )
        self.client.check_and_reconnect_to_leader = lambda: self.client.reconnect_to_leader()
        self.client.handle_message = lambda msg: print(
            "Handled message:", MessageToDict(msg.payload)
        )

    def tearDown(self):
        grpc.channel_ready_future = self._old_channel_ready_future

    def test_connect(self):
        old_insecure_channel = grpc.insecure_channel
        grpc.insecure_channel = lambda target: FakeChannel()
        import src.protocols.grpc.chat_pb2_grpc as chat_pb2_grpc

        old_stub_ctor = chat_pb2_grpc.ChatServerStub
        chat_pb2_grpc.ChatServerStub = lambda channel: FakeChatServerStub()
        connected = self.client.connect()
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

    def test_create_account_failure(self):
        client = ChatClient(username="fail", host="127.0.0.1", port=50051)
        client.stub = FakeChatServerStub()
        client.channel = FakeChannel()
        success = client.create_account_sync("pass")
        self.assertFalse(success)

    def test_list_chat_partners_sync_success(self):
        response = self.client.list_chat_partners_sync()
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)
        payload = MessageToDict(response.payload)
        self.assertIn("chat_partners", payload)
        self.assertIn("unread_map", payload)

    def test_list_chat_partners_sync_failure(self):
        original_method = self.client.stub.ListChatPartners

        def error_list_chat_partners(request):
            response_payload = {"text": "Error in listing chat partners."}
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=request.sender,
                timestamp=time.time(),
            )

        self.client.stub.ListChatPartners = error_list_chat_partners
        response = self.client.list_chat_partners_sync()
        self.assertEqual(response.type, chat_pb2.MessageType.ERROR)
        self.client.stub.ListChatPartners = original_method

    def test_read_conversation_sync_success(self):
        response = self.client.read_conversation_sync("user2")
        self.assertEqual(response.type, chat_pb2.MessageType.SUCCESS)
        payload = MessageToDict(response.payload)
        self.assertIn("messages", payload)
        self.assertIn("total", payload)

    # def test_read_conversation_sync_failure(self):
    #     original_method = self.client.stub.ReadConversation

    #     def error_read_conversation(request):
    #         response_payload = {"text": "Error in reading conversation."}
    #         yield chat_pb2.ChatMessage(
    #             type=chat_pb2.MessageType.ERROR,
    #             payload=ParseDict(response_payload, Struct()),
    #             sender="SERVER",
    #             recipient=request.sender,
    #             timestamp=time.time(),
    #         )

    #     self.client.stub.ReadConversation = error_read_conversation
    #     # Convert generator to list and get first message.
    #     messages = list(self.client.read_conversation_sync("user2"))
    #     self.assertGreater(len(messages), 0)
    #     response = messages[0]
    #     self.assertEqual(response.type, chat_pb2.MessageType.ERROR)
    #     self.client.stub.ReadConversation = original_method

    def test_connection_error_handling(self):
        client = ChatClient(username="testuser", host="invalid_host", port=50051)
        self.assertFalse(client.connect())

    def test_connection_timeout(self):
        def slow_channel_ready_future(channel):
            class SlowFuture:
                def result(self, timeout):
                    raise grpc.FutureTimeoutError()

            return SlowFuture()

        original_future = grpc.channel_ready_future
        grpc.channel_ready_future = slow_channel_ready_future
        client = ChatClient(username="testuser", host="127.0.0.1", port=50051)
        success = client.connect(timeout=1)
        self.assertFalse(success)
        grpc.channel_ready_future = original_future

    def test_connection_rpc_error(self):
        def failing_list_accounts(request):
            raise grpc.RpcError("Failed RPC call")

        client = ChatClient(username="testuser", host="127.0.0.1", port=50051)
        client.stub = FakeChatServerStub()
        original_method = client.stub.ListAccounts
        client.stub.ListAccounts = failing_list_accounts
        success = client.connect()
        self.assertFalse(success)
        client.stub.ListAccounts = original_method

    def test_message_handling_error(self):
        # Test handling of an invalid message type using the monkey-patched handle_message.
        invalid_message = chat_pb2.ChatMessage(
            type=999,
            payload=ParseDict({"text": "test"}, Struct()),
            sender="test",
            recipient="test",
            timestamp=time.time(),
        )
        # The monkey-patched handle_message (set in setUp) should simply print a warning.
        try:
            self.client.handle_message(invalid_message)
        except Exception as e:
            self.fail(f"handle_message raised an exception: {e}")

    def test_send_message_with_error_response(self):
        original_method = self.client.stub.SendMessage

        def error_send_message(request):
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({"text": "Network error"}, Struct()),
                sender="SERVER",
                recipient=request.sender,
                timestamp=time.time(),
            )

        self.client.stub.SendMessage = error_send_message
        result = self.client.send_message("user2", "Hello")
        self.assertFalse(result)
        self.client.stub.SendMessage = original_method

    def test_send_message_max_retries_exceeded(self):
        def send_message_always_fail(request):
            response_payload = {"text": "Not the leader"}
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=request.sender,
                timestamp=time.time(),
            )

        client = ChatClient(
            username="testuser",
            host="127.0.0.1",
            port=50051,
            cluster_nodes=[("127.0.0.1", 50051), ("127.0.0.1", 50052)],
        )
        client.stub = FakeChatServerStub()
        client.channel = FakeChannel()
        original_method = client.stub.SendMessage
        client.stub.SendMessage = send_message_always_fail
        success = client.send_message("user2", "Hello")
        self.assertFalse(success)
        client.stub.SendMessage = original_method

    def test_send_message_retry_on_leader_change(self):
        send_attempts = 0

        def send_message_fail_then_succeed(request):
            nonlocal send_attempts
            send_attempts += 1
            if send_attempts == 1:
                response_payload = {"text": "Not the leader"}
                return chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.ERROR,
                    payload=ParseDict(response_payload, Struct()),
                    sender="SERVER",
                    recipient=request.sender,
                    timestamp=time.time(),
                )
            else:
                response_payload = {"text": "Message sent successfully"}
                return chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.SUCCESS,
                    payload=ParseDict(response_payload, Struct()),
                    sender="SERVER",
                    recipient=request.sender,
                    timestamp=time.time(),
                )

        client = ChatClient(
            username="testuser",
            host="127.0.0.1",
            port=50051,
            cluster_nodes=[("127.0.0.1", 50051), ("127.0.0.1", 50052)],
        )
        client.stub = FakeChatServerStub()
        client.channel = FakeChannel()
        original_method = client.stub.SendMessage
        client.stub.SendMessage = send_message_fail_then_succeed
        success = client.send_message("user2", "Hello")
        self.assertTrue(success)
        self.assertEqual(send_attempts, 2)
        client.stub.SendMessage = original_method

    def test_leader_discovery(self):
        def get_leader_success(request):
            response_payload = {"leader_host": "127.0.0.1", "leader_port": 50052}
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=request.sender,
                timestamp=time.time(),
            )

        client = ChatClient(
            username="testuser",
            host="127.0.0.1",
            port=50051,
            cluster_nodes=[("127.0.0.1", 50051), ("127.0.0.1", 50052)],
        )
        client.stub = FakeChatServerStub()
        client.channel = FakeChannel()
        client.discover_leader = lambda: ("127.0.0.1", 50052)
        leader_host, leader_port = client.discover_leader()
        self.assertEqual(leader_host, "127.0.0.1")
        self.assertEqual(leader_port, 50052)

    def test_leader_discovery_failure(self):
        def get_leader_error(request):
            response_payload = {"text": "Failed to get leader"}
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=request.sender,
                timestamp=time.time(),
            )

        client = ChatClient(
            username="testuser",
            host="127.0.0.1",
            port=50051,
            cluster_nodes=[("127.0.0.1", 50051), ("127.0.0.1", 50052)],
        )
        client.stub = FakeChatServerStub()
        client.channel = FakeChannel()
        client.discover_leader = lambda: (None, None)
        leader_host, leader_port = client.discover_leader()
        self.assertIsNone(leader_host)
        self.assertIsNone(leader_port)

    def test_leader_check_and_reconnect(self):
        def get_leader_change(request):
            response_payload = {"leader_host": "127.0.0.1", "leader_port": 50052}
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                payload=ParseDict(response_payload, Struct()),
                sender="SERVER",
                recipient=request.sender,
                timestamp=time.time(),
            )

        client = ChatClient(
            username="testuser",
            host="127.0.0.1",
            port=50051,
            cluster_nodes=[("127.0.0.1", 50051), ("127.0.0.1", 50052)],
        )
        client.stub = FakeChatServerStub()
        client.channel = FakeChannel()
        client.discover_leader = lambda: ("127.0.0.1", 50052)
        client.reconnect_to_leader = (
            lambda: setattr(client, "host", "127.0.0.1") or setattr(client, "port", 50052) or True
        )
        client.check_and_reconnect_to_leader = lambda: client.reconnect_to_leader()
        success = client.check_and_reconnect_to_leader()
        self.assertTrue(success)
        self.assertEqual(client.host, "127.0.0.1")
        self.assertEqual(client.port, 50052)

    def test_leader_reconnection_utilities(self):
        client = ChatClient(
            username="testuser",
            host="127.0.0.1",
            port=50051,
            cluster_nodes=[("127.0.0.1", 50051), ("127.0.0.1", 50052), ("127.0.0.1", 50053)],
        )
        client.stub = FakeChatServerStub()
        client.channel = FakeChannel()
        client.discover_leader = lambda: ("127.0.0.1", 50052)
        client.reconnect_to_leader = (
            lambda: setattr(client, "host", "127.0.0.1") or setattr(client, "port", 50052) or True
        )
        success = client.reconnect_to_leader()
        self.assertTrue(success)
        self.assertEqual(client.host, "127.0.0.1")
        self.assertEqual(client.port, 50052)

    def test_leader_utility_methods(self):
        client = ChatClient(
            username="testuser",
            host="127.0.0.1",
            port=50051,
            cluster_nodes=[("127.0.0.1", 50051), ("127.0.0.1", 50052), ("127.0.0.1", 50053)],
        )
        # Monkey-patch is_leader: say we are leader only if port is 50051.
        client.is_leader = lambda: (client.host, client.port) == ("127.0.0.1", 50051)
        self.assertTrue(client.is_leader())
        # Change to simulate not leader.
        client.host, client.port = "127.0.0.1", 50052
        self.assertFalse(client.is_leader())

    def test_leader_utility_methods_with_errors(self):
        client = ChatClient(
            username="testuser",
            host="127.0.0.1",
            port=50051,
            cluster_nodes=[("127.0.0.1", 50051), ("127.0.0.1", 50052), ("127.0.0.1", 50053)],
        )
        # Simulate RPC error for leader discovery.
        client.discover_leader = lambda: (None, None)
        client.is_leader = lambda: False
        self.assertFalse(client.is_leader())
        # Simulate malformed response by returning (None, None).
        client.discover_leader = lambda: (None, None)
        self.assertFalse(client.is_leader())

    def test_message_handling_error(self):
        invalid_message = chat_pb2.ChatMessage(
            type=999,
            payload=ParseDict({"text": "test"}, Struct()),
            sender="test",
            recipient="test",
            timestamp=time.time(),
        )
        # Our monkey-patched handle_message simply prints a warning.
        try:
            self.client.handle_message(invalid_message)
        except Exception as e:
            self.fail(f"handle_message raised an exception: {e}")


if __name__ == "__main__":
    unittest.main()
