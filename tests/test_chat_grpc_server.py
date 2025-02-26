import time
import uuid
import tempfile
import pytest
import grpc
from concurrent import futures
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

from src.protocols.grpc import chat_pb2, chat_pb2_grpc
from src.chat_grpc_server import ChatServer

# Returns a unique username to avoid collisions between tests.
def unique_username(base="testuser"):
    return f"{base}_{uuid.uuid4().hex[:8]}"

# Create a fixture to start a gRPC server instance using a temporary file-based database.
@pytest.fixture(scope="module")
def grpc_server_address():
    with tempfile.NamedTemporaryFile() as temp_db:
        db_path = temp_db.name
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        chat_server = ChatServer(db_path=db_path)
        chat_pb2_grpc.add_ChatServerServicer_to_server(chat_server, server)
        port = server.add_insecure_port("[::]:0")
        server.start()
        address = f"localhost:{port}"
        yield address
        server.stop(0)

# Create a stub fixture to use in tests.
@pytest.fixture
def stub(grpc_server_address):
    channel = grpc.insecure_channel(grpc_server_address)
    stub = chat_pb2_grpc.ChatServerStub(channel)
    yield stub
    channel.close()

# Helper functions for making RPC calls.
def create_account(stub, username, password):
    payload = {"username": username, "password": password}
    message = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.CREATE_ACCOUNT,
        payload=ParseDict(payload, Struct()),
        sender=username,
        recipient="SERVER",
        timestamp=time.time(),
    )
    return stub.CreateAccount(message)

def login(stub, username, password):
    payload = {"username": username, "password": password}
    message = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.LOGIN,
        payload=ParseDict(payload, Struct()),
        sender=username,
        recipient="SERVER",
        timestamp=time.time(),
    )
    return stub.Login(message)

def test_create_account_success(stub):
    username = unique_username("testuser")
    password = "password123"
    response = create_account(stub, username, password)
    result = MessageToDict(response.payload)
    # Expect a success message about account creation.
    assert "account created successfully" in result.get("text", "").lower()

def test_create_account_already_exists(stub):
    username = unique_username("duplicateuser")
    password = "password123"
    create_account(stub, username, password)
    # Try to create the account again.
    response = create_account(stub, username, password)
    result = MessageToDict(response.payload)
    assert "already exists" in result.get("text", "").lower()

def test_login_success(stub):
    username = unique_username("loginuser")
    password = "password123"
    create_account(stub, username, password)
    response = login(stub, username, password)
    result = MessageToDict(response.payload)
    assert "login successful" in result.get("text", "").lower()

def test_login_failure(stub):
    username = unique_username("nonexistent")
    password = "wrongpass"
    with pytest.raises(grpc.RpcError) as excinfo:
        login(stub, username, password)
    assert excinfo.value.code() == grpc.StatusCode.UNAUTHENTICATED

def test_send_message_and_read(stub):
    sender = unique_username("senderuser")
    recipient = unique_username("recipientuser")
    password = "password123"
    create_account(stub, sender, password)
    create_account(stub, recipient, password)
    
    text = "Hello, this is a test message."
    payload = {"text": text}
    message = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.SEND_MESSAGE,
        payload=ParseDict(payload, Struct()),
        sender=sender,
        recipient=recipient,
        timestamp=time.time(),
    )
    send_response = stub.SendMessage(message)
    result = MessageToDict(send_response.payload)
    assert "sent successfully" in result.get("text", "").lower()

    # Read undelivered messages for the recipient.
    read_request = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.READ_MESSAGES,
        payload=Struct(),
        sender=recipient,
        recipient=recipient,
        timestamp=time.time(),
    )
    responses = stub.ReadMessages(read_request)
    msg = next(responses)
    payload_dict = MessageToDict(msg.payload)
    assert text in payload_dict.get("text", "")

def test_delete_messages(stub):
    sender = unique_username("deletemsgsender")
    recipient = unique_username("deletemsgrecipient")
    password = "password123"
    create_account(stub, sender, password)
    create_account(stub, recipient, password)
    
    text = "Message to delete"
    payload = {"text": text}
    message = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.SEND_MESSAGE,
        payload=ParseDict(payload, Struct()),
        sender=sender,
        recipient=recipient,
        timestamp=time.time(),
    )
    stub.SendMessage(message)
    
    # Retrieve the message to obtain its ID.
    read_request = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.READ_MESSAGES,
        payload=Struct(),
        sender=recipient,
        recipient=recipient,
        timestamp=time.time(),
    )
    responses = stub.ReadMessages(read_request)
    msg = next(responses)
    payload_dict = MessageToDict(msg.payload)
    message_id = payload_dict.get("id")
    assert message_id is not None

    # Delete the message by its ID.
    payload_del = {"message_ids": [message_id]}
    del_message = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.DELETE_MESSAGES,
        payload=ParseDict(payload_del, Struct()),
        sender=sender,
        recipient="SERVER",
        timestamp=time.time(),
    )
    del_response = stub.DeleteMessages(del_message)
    result = MessageToDict(del_response.payload)
    assert "deleted successfully" in result.get("text", "").lower()

def test_delete_account(stub):
    username = unique_username("deleteaccountuser")
    password = "password123"
    create_account(stub, username, password)
    
    del_message = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.DELETE_ACCOUNT,
        payload=Struct(),
        sender=username,
        recipient="SERVER",
        timestamp=time.time(),
    )
    del_response = stub.DeleteAccount(del_message)
    result = MessageToDict(del_response.payload)
    assert "deleted successfully" in result.get("text", "").lower()

def test_list_chat_partners(stub):
    user1 = unique_username("chatpartner1")
    user2 = unique_username("chatpartner2")
    password = "password123"
    create_account(stub, user1, password)
    create_account(stub, user2, password)
    
    payload = {"text": "Hi from user1"}
    message = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.SEND_MESSAGE,
        payload=ParseDict(payload, Struct()),
        sender=user1,
        recipient=user2,
        timestamp=time.time(),
    )
    stub.SendMessage(message)
    
    # List chat partners for user2.
    list_request = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.LIST_CHAT_PARTNERS,
        payload=Struct(),
        sender=user2,
        recipient="SERVER",
        timestamp=time.time(),
    )
    response = stub.ListChatPartners(list_request)
    result = MessageToDict(response.payload)
    chat_partners = result.get("chat_partners", [])
    assert user1 in chat_partners

def test_read_conversation(stub):
    user1 = unique_username("convuser1")
    user2 = unique_username("convuser2")
    password = "password123"
    create_account(stub, user1, password)
    create_account(stub, user2, password)
    
    # Send two messages from user1 to user2.
    messages = ["Hello", "How are you?"]
    for text in messages:
        payload = {"text": text}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SEND_MESSAGE,
            payload=ParseDict(payload, Struct()),
            sender=user1,
            recipient=user2,
            timestamp=time.time(),
        )
        stub.SendMessage(message)
    
    # Read the conversation from user1's perspective.
    payload_conv = {"partner": user2, "offset": 0, "limit": 10}
    conv_message = chat_pb2.ChatMessage(
        type=chat_pb2.MessageType.READ_MESSAGES,
        payload=ParseDict(payload_conv, Struct()),
        sender=user1,
        recipient="SERVER",
        timestamp=time.time(),
    )
    response = stub.ReadConversation(conv_message, None)
    result = MessageToDict(response.payload)
    conv_messages = result.get("messages", [])
    # Check that at least as many messages are returned as were sent.
    assert len(conv_messages) >= len(messages)
