import time
import pytest
from unittest.mock import MagicMock
import grpc
from google.protobuf.json_format import ParseDict, MessageToDict
from google.protobuf.struct_pb2 import Struct

from src.chat_grpc_client import ChatClient
from src.protocols.grpc import chat_pb2

# ----------------- Dummy Stub Fixture -----------------

@pytest.fixture
def dummy_stub():
    stub = MagicMock()

    # Successful responses.
    stub.CreateAccount.return_value = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.SUCCESS,
        payload=ParseDict({"text": "Account created successfully."}, Struct()),
        sender="SERVER",
        recipient="dummy",
        timestamp=time.time(),
    )
    stub.Login.return_value = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.SUCCESS,
        payload=ParseDict({"text": "Login successful. You have 0 unread messages."}, Struct()),
        sender="SERVER",
        recipient="dummy",
        timestamp=time.time(),
    )
    stub.SendMessage.return_value = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.SUCCESS,
        payload=ParseDict({"text": "Message sent successfully."}, Struct()),
        sender="SERVER",
        recipient="dummy",
        timestamp=time.time(),
    )
    stub.ListAccounts.return_value = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.SUCCESS,
        payload=ParseDict({"users": ["user1", "user2"]}, Struct()),
        sender="SERVER",
        recipient="dummy",
        timestamp=time.time(),
    )
    stub.DeleteMessages.return_value = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.SUCCESS,
        payload=ParseDict({"text": "Messages deleted successfully."}, Struct()),
        sender="SERVER",
        recipient="dummy",
        timestamp=time.time(),
    )
    stub.DeleteAccount.return_value = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.SUCCESS,
        payload=ParseDict({"text": "Account deleted successfully."}, Struct()),
        sender="SERVER",
        recipient="dummy",
        timestamp=time.time(),
    )
    stub.ListChatPartners.return_value = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.SUCCESS,
        payload=ParseDict({"chat_partners": ["partner1", "partner2"],
                           "unread_map": {"partner1": 1}}, Struct()),
        sender="SERVER",
        recipient="dummy",
        timestamp=time.time(),
    )
    stub.ReadConversation.return_value = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.SUCCESS,
        payload=ParseDict({"messages": [{"id": 1, "from": "partner1", "content": "Hello", "timestamp": time.time()}],
                           "total": 1}, Struct()),
        sender="SERVER",
        recipient="dummy",
        timestamp=time.time(),
    )
    # For ReadMessages streaming RPC, yield one message.
    def read_messages_gen(request, timeout=None):
        msg_payload = ParseDict({"text": "Test message", "id": 42}, Struct())
        yield chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SEND_MESSAGE,
            payload=msg_payload,
            sender="partner",
            recipient=request.recipient,
            timestamp=time.time(),
        )
    stub.ReadMessages.side_effect = read_messages_gen

    return stub

# ----------------- Client Fixture With Dummy Stub -----------------

@pytest.fixture
def client_with_dummy(monkeypatch, dummy_stub):
    # Override grpc.channel_ready_future so that connect() always returns ready.
    monkeypatch.setattr(grpc, "channel_ready_future",
                        lambda channel: type("DummyFuture", (), {"result": lambda self, timeout=None: True})())
    client = ChatClient(username="test_user", host="mock_host", port=12345)
    # Replace the real stub with our dummy stub.
    client.stub = dummy_stub
    return client

# ----------------- Tests for Successful Responses -----------------

def test_connect(client_with_dummy):
    assert client_with_dummy.connect() is True

def test_create_account(client_with_dummy, capsys):
    client_with_dummy.create_account("password")
    captured = capsys.readouterr().out.lower()
    assert "account created successfully" in captured

def test_create_account_sync(client_with_dummy):
    result = client_with_dummy.create_account_sync("password")
    assert result is True

def test_login_success(client_with_dummy):
    success, err = client_with_dummy.login_sync("password")
    assert success is True
    assert err is None
    assert client_with_dummy.logged_in is True

def test_send_message_success(client_with_dummy, capsys):
    response = client_with_dummy.send_message_sync("recipient", "Hello")
    resp_text = MessageToDict(response.payload).get("text", "").lower()
    assert response.type == chat_pb2.MessageType.SUCCESS
    assert "message sent successfully" in resp_text

def test_list_accounts(client_with_dummy):
    response = client_with_dummy.list_accounts_sync("user", 1)
    users = MessageToDict(response.payload).get("users", [])
    assert "user1" in users and "user2" in users

def test_delete_messages_success(client_with_dummy, capsys):
    response = client_with_dummy.delete_messages_sync([1, 2])
    resp_text = MessageToDict(response.payload).get("text", "").lower()
    assert "messages deleted successfully" in resp_text

def test_delete_account_success(client_with_dummy, capsys):
    response = client_with_dummy.delete_account_sync()
    resp_text = MessageToDict(response.payload).get("text", "").lower()
    assert "account deleted successfully" in resp_text

def test_list_chat_partners(client_with_dummy):
    response = client_with_dummy.list_chat_partners_sync()
    data = MessageToDict(response.payload)
    assert "partner1" in data.get("chat_partners", [])

def test_read_conversation_success(client_with_dummy):
    response = client_with_dummy.read_conversation_sync("partner1", 0, 50)
    data = MessageToDict(response.payload)
    messages = data.get("messages", [])
    assert len(messages) > 0
    # Check that the conversation message contains "hello"
    assert "hello" in messages[0].get("content", "").lower()

def test_read_messages_success(client_with_dummy, capsys):
    request = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.READ_MESSAGES,
        payload=Struct(),
        sender="test_user",
        recipient="test_user",
        timestamp=time.time(),
    )
    gen = client_with_dummy.stub.ReadMessages(request)
    message = next(gen)
    msg_text = MessageToDict(message.payload).get("text", "").lower()
    assert "test message" in msg_text

def test_start_read_thread(client_with_dummy):
    client_with_dummy.start_read_thread()
    time.sleep(0.2)
    assert not client_with_dummy.incoming_messages_queue.empty()

def test_close(client_with_dummy):
    # Ensure that calling close does not raise an exception.
    client_with_dummy.close()

# ----------------- Tests for Error/Failure Responses -----------------

def test_connect_failure(monkeypatch, client_with_dummy):
    # Simulate failure by making stub.ListAccounts raise an RpcError.
    def raise_rpc(*args, **kwargs):
        raise grpc.RpcError("Simulated RPC error")
    client_with_dummy.stub.ListAccounts.side_effect = raise_rpc
    result = client_with_dummy.connect()
    assert result is False

def test_login_failure(monkeypatch, client_with_dummy, capsys):
    # Simulate a login failure response.
    client_with_dummy.stub.Login.return_value = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.ERROR,
        payload=ParseDict({"text": "Login failed."}, Struct()),
        sender="SERVER",
        recipient="test_user",
        timestamp=time.time(),
    )
    success, err = client_with_dummy.login_sync("wrongpassword")
    assert success is False
    assert "login failed" in err.lower()

def test_send_message_failure(monkeypatch, client_with_dummy, capsys):
    # Simulate an RpcError in send_message.
    def raise_rpc(*args, **kwargs):
        raise grpc.RpcError("Simulated send error")
    client_with_dummy.stub.SendMessage.side_effect = raise_rpc
    result = client_with_dummy.send_message("recipient", "Hello")
    assert result is False

def test_read_conversation_failure(monkeypatch, client_with_dummy, capsys):
    # Simulate a non-success response for ReadConversation.
    client_with_dummy.stub.ReadConversation.return_value = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.ERROR,
        payload=ParseDict({"text": "Failed to read conversation."}, Struct()),
        sender="SERVER",
        recipient="test_user",
        timestamp=time.time(),
    )
    conv = client_with_dummy.read_conversation("partner1", 0, 50)
    # Expect an empty list on failure.
    assert conv == []

def test_read_messages_error(monkeypatch, client_with_dummy, capsys):
    # Simulate an RpcError in the streaming ReadMessages call.
    def raise_rpc(*args, **kwargs):
        raise grpc.RpcError("Simulated stream error")
    client_with_dummy.stub.ReadMessages.side_effect = raise_rpc
    # Call read_messages() and capture output.
    client_with_dummy.incoming_messages_queue = __import__("queue").Queue()
    client_with_dummy.read_messages()
    captured = capsys.readouterr().out.lower()
    assert "message stream closed" in captured

def test_delete_messages_failure(monkeypatch, client_with_dummy, capsys):
    # Simulate a failure for delete_messages by returning an ERROR type.
    client_with_dummy.stub.DeleteMessages.return_value = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.ERROR,
        payload=ParseDict({"text": "Failed to delete messages."}, Struct()),
        sender="SERVER",
        recipient="test_user",
        timestamp=time.time(),
    )
    response = client_with_dummy.delete_messages_sync([1])
    resp_text = MessageToDict(response.payload).get("text", "").lower()
    assert "failed to delete messages" in resp_text

def test_delete_account_failure(monkeypatch, client_with_dummy, capsys):
    # Simulate a failure for delete_account by returning an ERROR type.
    client_with_dummy.stub.DeleteAccount.return_value = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.ERROR,
        payload=ParseDict({"text": "Failed to delete account."}, Struct()),
        sender="SERVER",
        recipient="test_user",
        timestamp=time.time(),
    )
    response = client_with_dummy.delete_account_sync()
    resp_text = MessageToDict(response.payload).get("text", "").lower()
    assert "failed to delete account" in resp_text
