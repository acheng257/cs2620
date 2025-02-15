import asyncio
import threading
import time
from typing import Generator
from unittest.mock import Mock, patch

import pytest

from src.client import ChatClient
from src.protocols.base import Message, MessageType, Protocol
from src.protocols.binary_protocol import BinaryProtocol
from src.protocols.json_protocol import JsonProtocol


@pytest.fixture
def mock_socket() -> Generator[Mock, None, None]:
    with patch("socket.socket") as mock:
        # Configure the mock to avoid connection closed messages
        mock.return_value.recv.return_value = b""
        yield mock


@pytest.fixture
def client(mock_socket: Mock) -> ChatClient:
    client = ChatClient("test_user", "json")
    return client


@pytest.fixture
def connected_client(client: ChatClient, mock_socket: Mock) -> ChatClient:
    mock_socket.return_value.connect.return_value = None
    client.connect()
    return client


def create_mock_message(mock_socket: Mock, message: Message, protocol: Protocol) -> bytes:
    """Helper function to create properly formatted mock message data."""
    serialized = protocol.serialize(message)
    length = len(serialized)
    length_bytes = length.to_bytes(4, "big")
    mock_socket.return_value.sendall.return_value = None
    return length_bytes + serialized


class TestChatClient:
    def test_init_with_json_protocol(self) -> None:
        """Test client initialization with JSON protocol."""
        client = ChatClient("test_user", "json")
        assert isinstance(client.protocol, JsonProtocol)
        assert client.protocol_byte == b"J"
        assert client.username == "test_user"
        assert not client.logged_in

    def test_init_with_binary_protocol(self) -> None:
        """Test client initialization with Binary protocol."""
        client = ChatClient("test_user", "binary")
        assert isinstance(client.protocol, BinaryProtocol)
        assert client.protocol_byte == b"B"
        assert client.username == "test_user"
        assert not client.logged_in

    def test_connect_success(self, mock_socket: Mock) -> None:
        """Test successful connection to server."""
        client = ChatClient("test_user", "json")
        mock_socket.return_value.connect.return_value = None
        # Mock the receive behavior to keep the client running
        mock_socket.return_value.recv.side_effect = [b"test"]  # Return some data first

        assert client.connect() is True
        assert client.running is True
        assert client.receive_thread is not None
        assert client.receive_thread.is_alive()

        # Clean up
        client.running = False
        client.receive_thread.join(timeout=1.0)

    def test_connect_failure(self, mock_socket: Mock) -> None:
        """Test connection failure handling."""
        client = ChatClient("test_user", "json")
        mock_socket.return_value.connect.side_effect = Exception("Connection failed")

        assert client.connect() is False
        assert client.running is False
        assert client.receive_thread is None

    def test_create_account(self, connected_client: ChatClient, mock_socket: Mock) -> None:
        """Test account creation message sending."""
        message = Message(
            type=MessageType.CREATE_ACCOUNT,
            payload={"username": "test_user", "password": "password123"},
            sender="test_user",
            recipient="SERVER",
        )
        create_mock_message(mock_socket, message, connected_client.protocol)
        mock_socket.return_value.sendall.return_value = None

        assert connected_client.create_account("password123") is True

        # Verify the message was sent correctly
        mock_socket.return_value.sendall.assert_called()
        sent_data = mock_socket.return_value.sendall.call_args_list[-1][0][0]
        assert len(sent_data) > 4  # Should have length prefix

    def test_login(self, connected_client: ChatClient, mock_socket: Mock) -> None:
        """Test login message sending."""
        message = Message(
            type=MessageType.LOGIN,
            payload={"username": "test_user", "password": "password123"},
            sender="test_user",
            recipient="SERVER",
        )
        create_mock_message(mock_socket, message, connected_client.protocol)
        mock_socket.return_value.sendall.return_value = None

        assert connected_client.login("password123") is True

        # Verify the message was sent correctly
        mock_socket.return_value.sendall.assert_called()
        sent_data = mock_socket.return_value.sendall.call_args_list[-1][0][0]
        assert len(sent_data) > 4  # Should have length prefix

    def test_send_message(self, connected_client: ChatClient, mock_socket: Mock) -> None:
        """Test sending a message to another user."""
        connected_client.logged_in = True
        message = Message(
            type=MessageType.SEND_MESSAGE,
            payload={"text": "Hello!"},
            sender="test_user",
            recipient="recipient",
        )
        create_mock_message(mock_socket, message, connected_client.protocol)
        mock_socket.return_value.sendall.return_value = None

        assert connected_client.send_message("recipient", "Hello!") is True

        # Verify the message was sent correctly
        mock_socket.return_value.sendall.assert_called()
        sent_data = mock_socket.return_value.sendall.call_args_list[-1][0][0]
        assert len(sent_data) > 4  # Should have length prefix

    def test_send_message_not_logged_in(self, connected_client: ChatClient) -> None:
        """Test sending a message while not logged in."""
        connected_client.logged_in = False
        assert connected_client.send_message("recipient", "Hello!") is False

    def test_delete_account_not_logged_in(self, connected_client: ChatClient) -> None:
        """Test account deletion while not logged in."""
        connected_client.logged_in = False
        assert connected_client.delete_account() is False

    def test_delete_account(self, connected_client: ChatClient, mock_socket: Mock) -> None:
        """Test successful account deletion when logged in using a \
            simulated server response via Timer."""
        connected_client.logged_in = True

        # Ensure the receive thread from connect() is running
        if not connected_client.running or connected_client.receive_thread is None:
            connected_client.running = True
            connected_client.receive_thread = threading.Thread(
                target=connected_client.receive_messages, daemon=True
            )
            connected_client.receive_thread.start()

        # Create success response message
        response_message = Message(
            type=MessageType.SUCCESS,
            payload={"message": "Account deleted successfully"},
            sender="SERVER",
            recipient="test_user",
        )

        # Instead of faking socket.recv, simulate the server response
        #  by setting last_response after a short delay
        threading.Timer(
            0.1, lambda: setattr(connected_client, "last_response", response_message)
        ).start()

        mock_socket.return_value.sendall.return_value = None

        result = connected_client.delete_account()

        # Clean up
        connected_client.running = False
        if connected_client.receive_thread is not None:
            connected_client.receive_thread.join(timeout=1.0)

        assert result is True

    @pytest.mark.asyncio
    async def test_receive_messages(self, connected_client: ChatClient, mock_socket: Mock) -> None:
        """Test message receiving functionality."""
        # Prepare a test message
        test_message = Message(
            type=MessageType.SEND_MESSAGE,
            payload={"text": "Hello!", "id": 123},
            sender="other_user",
            recipient="test_user",
        )
        serialized_msg = connected_client.protocol.serialize(test_message)
        msg_length = len(serialized_msg)

        # Create a complete message with length prefix
        complete_message = msg_length.to_bytes(4, "big") + serialized_msg

        # Set up the mock to return the complete message first, then empty string to stop
        mock_socket.return_value.recv.side_effect = [
            complete_message[:4],  # Length prefix
            complete_message[4:],  # Message content
            b"",  # End the receive loop
        ]

        # Start receiving messages in a separate thread
        connected_client.running = True  # Ensure the client is running
        receive_thread = threading.Thread(target=connected_client.receive_messages)
        receive_thread.daemon = True
        receive_thread.start()

        # Wait for the message to be processed
        received_msg = None
        for _ in range(10):  # Try for 1 second (10 * 0.1s)
            try:
                received_msg = connected_client.incoming_messages_queue.get_nowait()
                break
            except:  # noqa: E722
                await asyncio.sleep(0.1)

        # Stop the receive thread
        connected_client.running = False
        receive_thread.join(timeout=1.0)

        assert received_msg is not None
        assert received_msg.type == test_message.type
        assert received_msg.payload == test_message.payload
        assert received_msg.sender == test_message.sender
        assert received_msg.recipient == test_message.recipient

    def test_list_accounts_sync(self, connected_client: ChatClient, mock_socket: Mock) -> None:
        """Test synchronous account listing."""
        # Prepare a response message
        response = Message(
            type=MessageType.LIST_ACCOUNTS,
            payload={"accounts": ["user1", "user2"]},
            sender="SERVER",
            recipient="test_user",
        )

        # Mock the response
        def mock_receive() -> None:
            with connected_client.response_lock:
                connected_client.last_response = response

        threading.Timer(0.1, mock_receive).start()

        result = connected_client.list_accounts_sync()
        assert result is not None
        assert result.type == MessageType.LIST_ACCOUNTS
        assert result.payload["accounts"] == ["user1", "user2"]

    def test_read_conversation_sync(self, connected_client: ChatClient, mock_socket: Mock) -> None:
        """Test synchronous conversation reading."""
        # Prepare a response message
        response = Message(
            type=MessageType.READ_MESSAGES,
            payload={"messages": [{"text": "Hello!", "timestamp": time.time()}]},
            sender="SERVER",
            recipient="test_user",
        )

        # Mock the response
        def mock_receive() -> None:
            with connected_client.response_lock:
                connected_client.last_response = response

        threading.Timer(0.1, mock_receive).start()

        result = connected_client.read_conversation_sync("other_user")
        assert result is not None
        assert result.type == MessageType.READ_MESSAGES
        assert len(result.payload["messages"]) == 1

    def test_close(self, connected_client: ChatClient, mock_socket: Mock) -> None:
        """Test client connection closing."""
        # Reset the mock to clear any previous calls
        mock_socket.return_value.close.reset_mock()

        # Ensure client is in a clean state
        connected_client.running = True

        # Close the connection
        connected_client.close()

        # Verify the state and socket closure
        assert connected_client.running is False
        mock_socket.return_value.close.assert_called_once()

    def test_list_chat_partners_sync(self, connected_client: ChatClient, mock_socket: Mock) -> None:
        """Test synchronous listing of chat partners."""
        # Create expected response message
        response_message = Message(
            type=MessageType.LIST_CHAT_PARTNERS,
            payload={"partners": ["user1", "user2", "user3"]},
            sender="SERVER",
            recipient="test_user",
        )

        # Schedule simulated server response
        def set_response() -> None:
            with connected_client.response_lock:
                connected_client.last_response = response_message

        threading.Timer(0.1, set_response).start()

        # Call the method and verify response
        result = connected_client.list_chat_partners_sync()
        assert result is not None
        assert result.type == MessageType.LIST_CHAT_PARTNERS
        assert "partners" in result.payload
        assert len(result.payload["partners"]) == 3
        assert "user1" in result.payload["partners"]
        assert "user2" in result.payload["partners"]
        assert "user3" in result.payload["partners"]

    def test_delete_messages_sync(self, connected_client: ChatClient, mock_socket: Mock) -> None:
        """Test synchronous message deletion."""
        connected_client.logged_in = True
        message_ids = [1, 2, 3]

        # Create success response message
        response_message = Message(
            type=MessageType.SUCCESS,
            payload={"message": "Messages deleted successfully"},
            sender="SERVER",
            recipient="test_user",
        )

        # Schedule simulated server response
        def set_response() -> None:
            with connected_client.response_lock:
                connected_client.last_response = response_message

        threading.Timer(0.1, set_response).start()

        # Call the method and verify response
        result = connected_client.delete_messages_sync(message_ids)
        assert result is True

        # Verify the correct message was sent
        mock_socket.return_value.sendall.assert_called()
        sent_data = mock_socket.return_value.sendall.call_args_list[-1][0][0]
        assert len(sent_data) > 4  # Should have length prefix

    def test_delete_messages_sync_not_logged_in(self, connected_client: ChatClient) -> None:
        """Test message deletion when not logged in."""
        connected_client.logged_in = False
        result = connected_client.delete_messages_sync([1, 2, 3])
        assert result is False
