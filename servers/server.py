import socket
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from protocols.base import Message, MessageType, Protocol
from protocols.binary_protocol import BinaryProtocol
from protocols.json_protocol import JsonProtocol
from src.database.db_manager import DatabaseManager


@dataclass
class User:
    username: str
    password_hash: bytes
    messages: List[Dict]


@dataclass
class ClientConnection:
    socket: socket.socket
    protocol: Protocol
    username: Optional[str] = None


class ChatServer:
    def __init__(
        self, host: str = "127.0.0.1", port: int = 54400, db_path: str = "chat.db"
    ) -> None:
        self.host = host
        self.port = port
        self.active_connections: Dict[socket.socket, ClientConnection] = {}
        self.username_to_socket: Dict[str, socket.socket] = {}
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))
        self.lock = threading.Lock()
        self.db = DatabaseManager(db_path)

    def send_response(
        self, client_socket: socket.socket, message_type: MessageType, content: str
    ) -> None:
        """Send a response message to a client."""
        connection = self.active_connections[client_socket]
        response = Message(
            type=message_type,
            payload={"text": content},
            sender="SERVER",
            recipient=connection.username or "unknown",
            timestamp=time.time(),
        )
        data = connection.protocol.serialize(response)
        length = len(data)
        client_socket.send(length.to_bytes(4, "big"))
        client_socket.send(data)

    def handle_create_account(self, client_socket: socket.socket, message: Message) -> None:
        """Handle account creation request."""
        username = message.payload.get("username")
        password = message.payload.get("password")

        if not username or not password:
            self.send_response(client_socket, MessageType.ERROR, "Username and password required")
            return

        if self.db.create_account(username, password):
            self.active_connections[client_socket].username = username
            with self.lock:
                self.username_to_socket[username] = client_socket
            self.send_response(client_socket, MessageType.SUCCESS, "Account created successfully")
        else:
            self.send_response(client_socket, MessageType.ERROR, "Username already exists")

    def handle_login(self, client_socket: socket.socket, message: Message) -> None:
        """Handle login request."""
        username = message.payload.get("username")
        password = message.payload.get("password")

        if not username or not password:
            self.send_response(client_socket, MessageType.ERROR, "Username and password required")
            return

        if self.db.verify_login(username, password):
            # Set up the connection
            self.active_connections[client_socket].username = username
            with self.lock:
                self.username_to_socket[username] = client_socket

            # Get unread message count
            unread_count = self.db.get_unread_message_count(username)
            self.send_response(
                client_socket,
                MessageType.SUCCESS,
                f"Login successful. You have {unread_count} unread messages.",
            )
        else:
            self.send_response(client_socket, MessageType.ERROR, "Invalid username or password")

    def handle_delete_account(self, client_socket: socket.socket, message: Message) -> None:
        """Handle account deletion request."""
        connection = self.active_connections[client_socket]
        if not connection.username:
            self.send_response(client_socket, MessageType.ERROR, "Not logged in")
            return

        if self.db.delete_account(connection.username):
            self.send_response(client_socket, MessageType.SUCCESS, "Account deleted successfully")
            self.remove_client(client_socket)
        else:
            self.send_response(client_socket, MessageType.ERROR, "Failed to delete account")

    def send_direct_message(
        self, target_username: str, message_content: str, sender_username: str
    ) -> None:
        """Send a message to a specific client using the binary protocol."""
        if not self.db.user_exists(target_username):
            # Send error to sender
            sender_socket = self.username_to_socket[sender_username]
            self.send_response(
                sender_socket,
                MessageType.ERROR,
                f"User {target_username} does not exist",
            )
            return

        # Store message in database
        self.db.store_message(sender_username, target_username, message_content)

        # If user is online, send message immediately
        if target_username in self.username_to_socket:
            target_socket = self.username_to_socket[target_username]
            connection = self.active_connections[target_socket]

            message = Message(
                type=MessageType.SEND_MESSAGE,
                payload={"text": message_content},
                sender=sender_username,
                recipient=target_username,
                timestamp=time.time(),
            )

            try:
                data = connection.protocol.serialize(message)
                length = len(data)
                target_socket.send(length.to_bytes(4, "big"))
                target_socket.send(data)
            except Exception as e:
                print(f"Error sending to user {target_username}: {e}")
                self.remove_client(target_socket)

    def handle_client(self, client_socket: socket.socket) -> None:
        connection = self.active_connections[client_socket]
        try:
            while True:
                length_bytes = client_socket.recv(4)
                if not length_bytes:
                    print("Client disconnected.")
                    break

                message_length = int.from_bytes(length_bytes, "big")

                message_data = b""
                while len(message_data) < message_length:
                    chunk = client_socket.recv(message_length - len(message_data))
                    if not chunk:
                        print("Client disconnected during message reception.")
                        break
                    message_data += chunk

                if len(message_data) < message_length:
                    break

                message = connection.protocol.deserialize(message_data)

                # Handle different message types
                if message.type == MessageType.CREATE_ACCOUNT:
                    self.handle_create_account(client_socket, message)
                elif message.type == MessageType.LOGIN:
                    self.handle_login(client_socket, message)
                elif message.type == MessageType.DELETE_ACCOUNT:
                    self.handle_delete_account(client_socket, message)
                elif message.type == MessageType.SEND_MESSAGE:
                    if not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in")
                        continue
                    if not message.recipient:
                        self.send_response(
                            client_socket, MessageType.ERROR, "No recipient specified"
                        )
                        continue
                    self.send_direct_message(
                        message.recipient, message.payload["text"], connection.username
                    )

        except Exception as e:
            print(f"Error handling client: {e}")
        finally:
            self.remove_client(client_socket)

    def remove_client(self, client_socket: socket.socket) -> None:
        """Remove a client from active connections."""
        with self.lock:
            if client_socket in self.active_connections:
                username = self.active_connections[client_socket].username
                if username in self.username_to_socket:
                    del self.username_to_socket[username]
                del self.active_connections[client_socket]
                try:
                    client_socket.close()
                except Exception as e:
                    print(f"Error closing client socket: {e}")

    def start(self) -> None:
        """Start the server."""
        self.socket.listen(5)
        print(f"Server started on {self.host}:{self.port}")

        while True:
            client_socket, address = self.socket.accept()
            print(f"New connection from {address}")

            protocol_byte = client_socket.recv(1)
            protocol = JsonProtocol() if protocol_byte == b"J" else BinaryProtocol()

            connection = ClientConnection(socket=client_socket, protocol=protocol)
            print(f"Using {connection.protocol.get_protocol_name()} protocol")
            with self.lock:
                self.active_connections[client_socket] = connection

            thread = threading.Thread(target=self.handle_client, args=(client_socket,))
            thread.daemon = True
            thread.start()


if __name__ == "__main__":
    server = ChatServer()
    server.start()
