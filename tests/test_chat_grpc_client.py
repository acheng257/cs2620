import time
import uuid
import tempfile
import threading
import pytest
import grpc
from concurrent import futures

from src.protocols.grpc import chat_pb2_grpc
from src.chat_grpc_client import ChatClient  # your client class
from src.chat_grpc_server import ChatServer  # the gRPC server implementation

# Helper to generate unique usernames.
def unique_username(base="client"):
    return f"{base}_{uuid.uuid4().hex[:8]}"

# Fixture to start a gRPC server with a temporary file-based SQLite DB.
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

# Fixture for a ChatClient instance.
@pytest.fixture
def client(grpc_server_address):
    host, port_str = grpc_server_address.split(":")
    port = int(port_str)
    username = unique_username("testclient")
    c = ChatClient(username=username, host=host, port=port)
    yield c
    c.close()

# Fixture for creating a second client.
@pytest.fixture
def second_client(grpc_server_address):
    host, port_str = grpc_server_address.split(":")
    port = int(port_str)
    username = unique_username("testclient2")
    c = ChatClient(username=username, host=host, port=port)
    yield c
    c.close()

# ------------------ Client Tests ------------------

def test_create_and_login(client, capsys):
    password = "password123"
    client.create_account(password)
    out = capsys.readouterr().out.lower()
    assert "account created successfully" in out or "already exists" in out

    logged_in = client.login(password)
    out = capsys.readouterr().out.lower()
    assert logged_in is True
    assert "login successful" in out

def test_send_message_and_read_conversation(grpc_server_address):
    host, port_str = grpc_server_address.split(":")
    port = int(port_str)
    password = "password123"
    sender_username = unique_username("sender")
    recipient_username = unique_username("recipient")
    
    sender = ChatClient(username=sender_username, host=host, port=port)
    recipient = ChatClient(username=recipient_username, host=host, port=port)
    
    # Create accounts and login.
    sender.create_account(password)
    recipient.create_account(password)
    assert sender.login(password) is True
    assert recipient.login(password) is True

    # Start recipient's read thread
    recipient.start_read_thread()
    time.sleep(0.1) 

    # Send a message.
    text = "Hello from sender!"
    sender.send_message(recipient_username, text)
    time.sleep(0.1)  # allow message delivery

    # Use read_conversation to verify message delivery.
    conv = sender.read_conversation(recipient_username)
    found = any(text in msg.get("content", "") for msg in conv)
    assert found

    sender.close()
    recipient.close()

def test_list_accounts(client, capsys):
    password = "password123"
    # Create several accounts with a common pattern.
    usernames = [unique_username("listuser") for _ in range(3)]
    for user in usernames:
        temp_client = ChatClient(username=user, host=client.host, port=client.port)
        temp_client.create_account(password)
        temp_client.close()

    # List accounts using the client's list_accounts() method.
    # This method prints the results, so capture stdout.
    client.list_accounts(pattern="listuser", page=1)
    out = capsys.readouterr().out.lower()
    for user in usernames:
        assert user.lower() in out

def test_delete_messages(grpc_server_address, capsys):
    host, port_str = grpc_server_address.split(":")
    port = int(port_str)
    password = "password123"
    sender = ChatClient(username=unique_username("delmsgsender"), host=host, port=port)
    recipient = ChatClient(username=unique_username("delmsgrecipient"), host=host, port=port)
    
    sender.create_account(password)
    recipient.create_account(password)
    assert sender.login(password)
    assert recipient.login(password)

    text = "Message to be deleted"
    sender.send_message(recipient.username, text)
    time.sleep(0.1)

    # Read the conversation to get message IDs.
    messages = sender.read_conversation(recipient.username)
    assert len(messages) > 0
    message_id = messages[0].get("id")
    assert message_id is not None

    # Call delete_messages.
    sender.delete_messages([message_id])
    out = capsys.readouterr().out.lower()
    assert "deleted successfully" in out

    sender.close()
    recipient.close()

def test_delete_account(grpc_server_address, capsys):
    host, port_str = grpc_server_address.split(":")
    port = int(port_str)
    password = "password123"
    username = unique_username("delaccount")
    temp_client = ChatClient(username=username, host=host, port=port)
    
    temp_client.create_account(password)
    assert temp_client.login(password)
    
    # Delete the account.
    temp_client.delete_account()
    out = capsys.readouterr().out.lower()
    assert "deleted successfully" in out
    temp_client.close()

def test_list_chat_partners(grpc_server_address, capsys):
    host, port_str = grpc_server_address.split(":")
    port = int(port_str)
    password = "password123"
    
    user1 = ChatClient(username=unique_username("partner1"), host=host, port=port)
    user2 = ChatClient(username=unique_username("partner2"), host=host, port=port)
    
    user1.create_account(password)
    user2.create_account(password)
    assert user1.login(password)
    assert user2.login(password)
    
    # Have user1 send a message to user2.
    user1.send_message(user2.username, "Hello partner!")
    time.sleep(0.1)
    
    # Call list_chat_partners which prints the partners.
    partners = user2.list_chat_partners()
    # Expect the returned dictionary to contain the chat partner.
    assert partners is not None
    assert user1.username in partners.get("chat_partners", [])
    
    user1.close()
    user2.close()

def test_start_read_thread_and_close(client, capsys):
    # This test calls start_read_thread and then immediately closes the client.
    password = "password123"
    client.create_account(password)
    client.login(password)
    client.start_read_thread()
    time.sleep(0.1)
    # Close the client; ensure no errors occur.
    client.close()
