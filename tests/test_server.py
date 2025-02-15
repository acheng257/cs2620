import threading
import time
from typing import Generator
from unittest.mock import Mock, patch

import pytest

from src.protocols.base import Message, MessageType
from src.protocols.json_protocol import JsonProtocol
from src.server import ChatServer, ClientConnection, User


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
    with patch("src.server.DatabaseManager", return_value=mock_db):
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
        mock_db.store_message.return_value = 1  # Set the return value for store_message

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

    def test_send_response_unknown_client(self, server: ChatServer) -> None:
        """Test sending response to unknown client."""
        client_socket = Mock()
        server.send_response(client_socket, MessageType.ERROR, "Test message")
        client_socket.sendall.assert_not_called()

    def test_send_response_failed_send(self, server: ChatServer) -> None:
        """Test handling failed message send."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )
        client_socket.sendall.side_effect = Exception("Send failed")

        server.send_response(client_socket, MessageType.SUCCESS, "Test message")
        assert client_socket not in server.active_connections

    def test_handle_create_account_missing_data(self, server: ChatServer) -> None:
        """Test account creation with missing data."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol
        )

        message = Message(
            type=MessageType.CREATE_ACCOUNT,
            payload={},  # Missing username and password
            sender=None,
            recipient=None,
        )

        server.handle_create_account(client_socket, message)
        assert client_socket.sendall.call_count == 2  # Error response sent

    def test_handle_login_missing_data(self, server: ChatServer) -> None:
        """Test login with missing data."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol
        )

        message = Message(
            type=MessageType.LOGIN,
            payload={},  # Missing username and password
            sender=None,
            recipient=None,
        )

        server.handle_login(client_socket, message)
        assert client_socket.sendall.call_count == 2  # Error response sent

    def test_deliver_undelivered_messages_no_socket(
        self, server: ChatServer, mock_db: Mock
    ) -> None:
        """Test delivering messages when user has no active socket."""
        mock_db.get_undelivered_messages.return_value = [
            {"id": 1, "from": "sender", "content": "Hello!", "timestamp": time.time()}
        ]
        server.deliver_undelivered_messages("offline_user")
        mock_db.mark_message_as_delivered.assert_not_called()

    def test_deliver_undelivered_messages_send_failure(
        self, server: ChatServer, mock_db: Mock
    ) -> None:
        """Test handling delivery failure for undelivered messages."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )
        server.username_to_socket["test_user"] = client_socket

        mock_db.get_undelivered_messages.return_value = [
            {"id": 1, "from": "sender", "content": "Hello!", "timestamp": time.time()}
        ]
        client_socket.sendall.side_effect = Exception("Send failed")

        server.deliver_undelivered_messages("test_user")
        assert client_socket not in server.active_connections

    def test_send_direct_message_nonexistent_user(self, server: ChatServer, mock_db: Mock) -> None:
        """Test sending message to non-existent user."""
        mock_db.user_exists.return_value = False
        sender_socket = Mock()
        server.username_to_socket["sender"] = sender_socket
        server.active_connections[sender_socket] = ClientConnection(
            socket=sender_socket, protocol=JsonProtocol(), username="sender"
        )

        server.send_direct_message("nonexistent", "Hello!", "sender")
        mock_db.store_message.assert_not_called()

    def test_handle_client_receive_error(self, server: ChatServer) -> None:
        """Test handling receive error in client handler."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )
        client_socket.recv.side_effect = Exception("Receive failed")

        server.handle_client(client_socket)
        assert client_socket not in server.active_connections

    def test_handle_client_invalid_message(self, server: ChatServer) -> None:
        """Test handling invalid message in client handler."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )

        # Mock receiving invalid message length
        client_socket.recv.side_effect = [b"\x00\x00\x00\x04", b"bad"]

        server.handle_client(client_socket)
        assert client_socket not in server.active_connections

    def test_handle_client_unknown_message_type(self, server: ChatServer) -> None:
        """Test handling unknown message type."""
        client_socket = Mock()
        protocol = JsonProtocol()
        connection = ClientConnection(socket=client_socket, protocol=protocol, username="test_user")
        server.active_connections[client_socket] = connection

        # Create a message with unknown type
        message = Message(
            type=MessageType.ERROR,  # Using ERROR as unknown type
            payload={},
            sender="test_user",
            recipient=None,
        )
        data = protocol.serialize(message)
        length = len(data)

        # Mock receiving the message
        client_socket.recv.side_effect = [
            length.to_bytes(4, "big"),
            data,
            b"",  # End the loop
        ]

        server.handle_client(client_socket)
        assert client_socket.sendall.call_count >= 2  # Error response sent

    def test_handle_read_messages_not_logged_in(self, server: ChatServer) -> None:
        """Test reading messages when not logged in."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol
        )

        message = Message(
            type=MessageType.READ_MESSAGES,
            payload={"otherUser": "other_user"},
            sender=None,
            recipient=None,
        )

        server.handle_read_messages(client_socket, message)
        assert client_socket.sendall.call_count == 2  # Error response sent

    def test_handle_delete_messages_invalid_ids(self, server: ChatServer) -> None:
        """Test deleting messages with invalid message IDs."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )

        message = Message(
            type=MessageType.DELETE_MESSAGES,
            payload={"message_ids": "not_a_list"},  # Invalid format
            sender="test_user",
            recipient=None,
        )

        server.handle_delete_messages(client_socket, message)
        assert client_socket.sendall.call_count == 2  # Error response sent

    def test_server_shutdown(self, server: ChatServer) -> None:
        """Test server shutdown process."""
        client_socket1 = Mock()
        client_socket2 = Mock()
        protocol = JsonProtocol()

        # Add some active connections
        server.active_connections[client_socket1] = ClientConnection(
            socket=client_socket1, protocol=protocol, username="user1"
        )
        server.active_connections[client_socket2] = ClientConnection(
            socket=client_socket2, protocol=protocol, username="user2"
        )
        server.username_to_socket["user1"] = client_socket1
        server.username_to_socket["user2"] = client_socket2

        server.shutdown()

        # Verify all connections were closed
        assert len(server.active_connections) == 0
        assert len(server.username_to_socket) == 0
        # TODO(@ItamarRocha): Maybe check to asset called once

    def test_handle_list_chat_partners(self, server: ChatServer, mock_db: Mock) -> None:
        """Test listing chat partners."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )

        mock_db.get_chat_partners.return_value = ["user1", "user2"]
        mock_db.get_unread_between_users.return_value = 5

        message = Message(
            type=MessageType.LIST_CHAT_PARTNERS,
            payload={},
            sender="test_user",
            recipient=None,
        )

        server.handle_list_chat_partners(client_socket, message)
        mock_db.get_chat_partners.assert_called_once_with("test_user")
        assert client_socket.sendall.call_count == 2  # Response sent

    def test_handle_list_chat_partners_not_logged_in(self, server: ChatServer) -> None:
        """Test listing chat partners when not logged in."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol
        )

        message = Message(
            type=MessageType.LIST_CHAT_PARTNERS,
            payload={},
            sender=None,
            recipient=None,
        )

        server.handle_list_chat_partners(client_socket, message)
        assert client_socket.sendall.call_count == 2  # Error response sent

    def test_user_dataclass(self) -> None:
        """Test User dataclass functionality."""
        user = User(username="test", password_hash=b"hash", messages=[])
        assert user.username == "test"
        assert user.password_hash == b"hash"
        assert user.messages == []

    def test_client_connection_dataclass(self) -> None:
        """Test ClientConnection dataclass functionality."""
        socket_mock = Mock()
        protocol = JsonProtocol()
        conn = ClientConnection(socket=socket_mock, protocol=protocol)
        assert conn.socket == socket_mock
        assert conn.protocol == protocol
        assert conn.username is None

    def test_receive_all_partial_data(self, server: ChatServer) -> None:
        """Test receiving data in chunks."""
        client_socket = Mock()
        client_socket.recv.side_effect = [b"pa", b"rt", b"ial"]
        data = server.receive_all(client_socket, 7)
        assert data == b"partial"
        assert client_socket.recv.call_count == 3

    def test_receive_all_connection_error(self, server: ChatServer) -> None:
        """Test receive_all with connection error."""
        client_socket = Mock()
        client_socket.recv.side_effect = ConnectionError("Connection lost")
        data = server.receive_all(client_socket, 5)
        assert data is None

    def test_receive_all_empty_data(self, server: ChatServer) -> None:
        """Test receive_all with empty data (connection closed)."""
        client_socket = Mock()
        client_socket.recv.return_value = b""
        data = server.receive_all(client_socket, 5)
        assert data is None

    def test_handle_client_connection_lost(self, server: ChatServer) -> None:
        """Test handling client when connection is lost."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )
        client_socket.recv.return_value = b""  # Simulate connection closed

        server.handle_client(client_socket)
        assert client_socket not in server.active_connections

    def test_deliver_undelivered_messages_invalid_timestamp(
        self, server: ChatServer, mock_db: Mock
    ) -> None:
        """Test delivering messages with invalid timestamp."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )
        server.username_to_socket["test_user"] = client_socket

        mock_db.get_undelivered_messages.return_value = [
            {"id": 1, "from": "sender", "content": "Hello!", "timestamp": "invalid"}
        ]

        server.deliver_undelivered_messages("test_user")
        assert client_socket.sendall.call_count == 2  # Message still sent with current timestamp

    def test_handle_client_protocol_error(self, server: ChatServer) -> None:
        """Test handling protocol deserialization error."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )

        # Mock receiving invalid protocol data
        client_socket.recv.side_effect = [
            (4).to_bytes(4, "big"),  # Length prefix
            b"invalid",  # Invalid protocol data
        ]

        server.handle_client(client_socket)
        assert client_socket not in server.active_connections

    def test_send_message_to_socket_no_connection(self, server: ChatServer) -> None:
        """Test sending message to socket with no connection."""
        client_socket = Mock()
        message = Message(
            type=MessageType.SUCCESS,
            payload={"text": "test"},
            sender="SERVER",
            recipient="test_user",
        )

        server.send_message_to_socket(client_socket, message)
        client_socket.sendall.assert_not_called()

    def test_handle_read_messages_db_error(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test handling database error during message reading."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )

        mock_db.get_messages_between_users.side_effect = Exception("Database error")

        message = Message(
            type=MessageType.READ_MESSAGES,
            payload={"otherUser": "other_user"},
            sender="test_user",
            recipient=None,
        )

        server.handle_read_messages(client_socket, message)
        assert client_socket.sendall.call_count == 2  # Error response sent

    def test_handle_delete_messages_db_error(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test handling database error during message deletion."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )

        mock_db.delete_messages.side_effect = Exception("Database error")

        message = Message(
            type=MessageType.DELETE_MESSAGES,
            payload={"message_ids": [1, 2, 3]},
            sender="test_user",
            recipient=None,
        )

        server.handle_delete_messages(client_socket, message)
        assert client_socket.sendall.call_count == 2  # Error response sent

    def test_handle_list_chat_partners_db_error(
        self, server: ChatServer, mock_socket: Mock, mock_db: Mock
    ) -> None:
        """Test handling database error during chat partner listing."""
        client_socket = Mock()
        protocol = JsonProtocol()
        server.active_connections[client_socket] = ClientConnection(
            socket=client_socket, protocol=protocol, username="test_user"
        )

        mock_db.get_chat_partners.side_effect = Exception("Database error")

        message = Message(
            type=MessageType.LIST_CHAT_PARTNERS,
            payload={},
            sender="test_user",
            recipient=None,
        )

        server.handle_list_chat_partners(client_socket, message)
        assert client_socket.sendall.call_count == 2  # Error response sent
