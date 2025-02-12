import threading
import time
from typing import Generator
from unittest.mock import Mock, patch

import pytest

from protocols.base import Message, MessageType
from protocols.json_protocol import JsonProtocol
from server import ChatServer, ClientConnection


@pytest.fixture
def mock_socket() -> Generator[Mock, None, None]:
    with patch("socket.socket") as mock:
        mock.return_value.accept.return_value = (Mock(), ("127.0.0.1", 12345))
        mock.return_value.recv.return_value = b""
        yield mock


@pytest.fixture
def mock_db() -> Generator[Mock, None, None]:
    with patch("src.database.db_manager.DatabaseManager") as mock_db_class:
        mock_db_instance = Mock()
        mock_db_class.return_value = mock_db_instance
        yield mock_db_instance


@pytest.fixture
def server(mock_socket: Mock, mock_db: Mock) -> ChatServer:
    with patch("server.DatabaseManager", return_value=mock_db):
        server = ChatServer(host="localhost", port=12345, db_path=":memory:")
        return server


class TestChatServer:
    def test_init(self, server: ChatServer) -> None:
        """Test server initialization."""
        assert server.host == "localhost"
        assert server.port == 12345
        assert isinstance(server.active_connections, dict)
        assert isinstance(server.username_to_socket, dict)
        assert isinstance(server.lock, threading.Lock)

    def test_send_response(self, server: ChatServer, mock_socket: Mock) -> None:
        """Test sending response to client."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )

        server.send_response(client_socket, MessageType.SUCCESS, "Test message")

        # Verify the message was sent correctly
        assert client_socket.sendall.call_count == 2  # Once for length, once for data
        calls = client_socket.sendall.call_args_list
        assert len(calls) == 2
        # First call should be length (4 bytes)
        assert len(calls[0][0][0]) == 4
        # Second call should be the serialized message
        assert len(calls[1][0][0]) > 0

    def test_handle_create_account_success(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test successful account creation."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol
        )

        mock_db.create_account.return_value = True

        message = Message(
            type=MessageType.CREATE_ACCOUNT,
            payload={"username": "test_user", "password": "password123"},
            sender=None,
            recipient=None,
        )

        server.handle_create_account(client_socket, message)

        mock_db.create_account.assert_called_once_with("test_user", "password123")
        assert server.active_connections[client_socket].username == "test_user"
        assert server.username_to_socket["test_user"] == client_socket

    def test_handle_create_account_failure(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test failed account creation."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol
        )

        mock_db.create_account.return_value = False

        message = Message(
            type=MessageType.CREATE_ACCOUNT,
            payload={"username": "test_user", "password": "password123"},
            sender=None,
            recipient=None,
        )

        server.handle_create_account(client_socket, message)

        mock_db.create_account.assert_called_once_with("test_user", "password123")
        assert client_socket.sendall.call_count == 2  # Error response sent

    def test_handle_login_success(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test successful login."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol
        )

        mock_db.verify_login.return_value = True
        mock_db.get_unread_message_count.return_value = 5
        mock_db.get_undelivered_messages.return_value = []

        message = Message(
            type=MessageType.LOGIN,
            payload={"username": "test_user", "password": "password123"},
            sender=None,
            recipient=None,
        )

        server.handle_login(client_socket, message)

        mock_db.verify_login.assert_called_once_with("test_user", "password123")
        assert server.active_connections[client_socket].username == "test_user"
        assert server.username_to_socket["test_user"] == client_socket

    def test_handle_login_failure(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test failed login."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol
        )

        mock_db.verify_login.return_value = False

        message = Message(
            type=MessageType.LOGIN,
            payload={"username": "test_user", "password": "wrong_password"},
            sender=None,
            recipient=None,
        )

        server.handle_login(client_socket, message)

        mock_db.verify_login.assert_called_once_with("test_user", "wrong_password")
        assert client_socket.sendall.call_count == 2  # Error response sent

    def test_handle_delete_account_success(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test successful account deletion."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )
        server.username_to_socket["test_user"] = client_socket

        mock_db.delete_account.return_value = True

        message = Message(
            type=MessageType.DELETE_ACCOUNT, payload={}, sender="test_user", recipient=None
        )

        server.handle_delete_account(client_socket, message)

        mock_db.delete_account.assert_called_once_with("test_user")
        assert client_socket not in server.active_connections
        assert "test_user" not in server.username_to_socket

    def test_send_direct_message_online_user(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test sending message to online user."""
        sender_socket = Mock()
        target_socket = Mock()
        protocol = JsonProtocol()

        # Set up connections
        server.active_connections[sender_socket] = ClientConnection(
            socket=sender_socket, protocol=protocol, username="sender"
        )
        server.active_connections[target_socket] = ClientConnection(
            socket=target_socket, protocol=protocol, username="target"
        )
        server.username_to_socket["sender"] = sender_socket
        server.username_to_socket["target"] = target_socket

        mock_db.user_exists.return_value = True
        mock_db.get_last_message_id.return_value = 1

        server.send_direct_message("target", "Hello!", "sender")

        mock_db.store_message.assert_called_once_with("sender", "target", "Hello!", True)
        mock_db.mark_message_as_delivered.assert_called_once_with(1)
        assert target_socket.sendall.call_count == 2  # Message sent to target

    def test_send_direct_message_offline_user(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test sending message to offline user."""
        sender_socket = Mock()
        protocol = JsonProtocol()

        # Set up sender connection
        server.active_connections[sender_socket] = ClientConnection(
            socket=sender_socket, protocol=protocol, username="sender"
        )
        server.username_to_socket["sender"] = sender_socket

        mock_db.user_exists.return_value = True

        server.send_direct_message("target", "Hello!", "sender")

        # Message should be stored as undelivered
        mock_db.store_message.assert_called_once_with("sender", "target", "Hello!", False)

    def test_handle_list_accounts(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test listing accounts."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )

        mock_db.list_accounts.return_value = ["user1", "user2", "user3"]

        message = Message(
            type=MessageType.LIST_ACCOUNTS,
            payload={"pattern": "*", "offset": "1", "limit": "10"},
            sender="test_user",
            recipient=None,
        )

        server.handle_list_accounts(client_socket, message)

        mock_db.list_accounts.assert_called_once_with("*", 1, 10)
        assert client_socket.sendall.call_count == 2  # Response sent

    def test_handle_read_messages(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test reading messages."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )

        mock_messages = {
            "messages": [
                {"id": 1, "from": "other_user", "content": "Hello!", "timestamp": time.time()}
            ],
            "total": 1,
        }
        mock_db.get_messages_between_users.return_value = mock_messages

        message = Message(
            type=MessageType.READ_MESSAGES,
            payload={"otherUser": "other_user", "offset": "0", "limit": "20"},
            sender="test_user",
            recipient=None,
        )

        server.handle_read_messages(client_socket, message)

        mock_db.get_messages_between_users.assert_called_once_with("test_user", "other_user", 0, 20)
        assert client_socket.sendall.call_count == 2  # Response sent

    def test_handle_delete_messages(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test deleting messages."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )

        mock_db.delete_messages.return_value = True

        message = Message(
            type=MessageType.DELETE_MESSAGES,
            payload={"message_ids": [1, 2, 3]},
            sender="test_user",
            recipient=None,
        )

        server.handle_delete_messages(client_socket, message)

        mock_db.delete_messages.assert_called_once_with("test_user", [1, 2, 3])
        assert client_socket.sendall.call_count == 2  # Success response sent

    def test_remove_client(self, server: ChatServer, mock_socket: Mock) -> None:
        """Test client removal."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )
        server.username_to_socket["test_user"] = client_socket

        server.remove_client(client_socket)

        assert client_socket not in server.active_connections
        assert "test_user" not in server.username_to_socket
        client_socket.close.assert_called_once()
