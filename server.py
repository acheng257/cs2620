# server.py
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
            connection = self.active_connections[client_socket]
            connection.username = username
            with self.lock:
                self.username_to_socket[username] = client_socket

            #Deliver any undelivered messages
            self.deliver_undelivered_messages(username)

            # Get unread message counts for all chat partners
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

        username = connection.username
        if self.db.delete_account(username):
            self.send_response(client_socket, MessageType.SUCCESS, "Account deleted successfully")
            self.remove_client(client_socket)
        else:
            self.send_response(client_socket, MessageType.ERROR, "Failed to delete account")

    def deliver_undelivered_messages(self, username: str) -> None:
        """Deliver undelivered messages to a user upon login."""
        undelivered_messages = self.db.get_undelivered_messages(username)
        for message in undelivered_messages:
            target_socket = self.username_to_socket.get(username)
            if target_socket:
                connection = self.active_connections[target_socket]

                msg = Message(
                    type=MessageType.SEND_MESSAGE,
                    payload={"text": message["content"]},
                    sender=message["from"],
                    recipient=username,
                    timestamp=message["timestamp"],
                )

                try:
                    data = connection.protocol.serialize(msg)
                    length = len(data)
                    target_socket.send(length.to_bytes(4, "big"))
                    target_socket.send(data)
                    self.db.mark_message_as_delivered(message["id"])  # Mark as delivered
                except Exception as e:
                    print(f"Error delivering undelivered message to {username}: {e}")
                    self.remove_client(target_socket)

    def send_direct_message(
        self, target_username: str, message_content: str, sender_username: str
    ) -> None:
        """Send a message to a specific client using the protocol."""
        if not self.db.user_exists(target_username):
            # Send error to sender
            sender_socket = self.username_to_socket[sender_username]
            self.send_response(
                sender_socket,
                MessageType.ERROR,
                f"User {target_username} does not exist",
            )
            return

        # Check if the target user is online
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

                self.db.store_message(sender_username, target_username, message_content, True) #Store message and set delivered to True
                self.db.mark_message_as_delivered(self.db.get_last_message_id(sender_username, target_username)) #Mark message as delivered
            except Exception as e:
                print(f"Error sending to user {target_username}: {e}")
                self.remove_client(target_socket)

        else:
            # Store message as undelivered
            self.db.store_message(sender_username, target_username, message_content, False) #Store message and set delivered to False
            print(f"User {target_username} is offline. Message stored as undelivered.")

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
                    connection = self.active_connections[client_socket] # re-acquire connection
                    self.deliver_undelivered_messages(connection.username) # deliver messages
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
                elif message.type == MessageType.LIST_ACCOUNTS:
                    if not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in")
                        continue
                    self.handle_list_accounts(client_socket, message)
                elif message.type == MessageType.READ_MESSAGES:
                    if not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in")
                        continue
                    self.handle_read_messages(client_socket, message)
                elif message.type == MessageType.DELETE_MESSAGES:
                    if not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in")
                        continue
                    self.handle_delete_messages(client_socket, message)
                elif message.type == MessageType.LIST_CHAT_PARTNERS:
                    self.handle_list_chat_partners(client_socket, message)
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

    def send_message_to_socket(self, client_socket: socket.socket, msg: Message) -> None:
        """
        A helper to serialize and send the given Message object
        to the specified client socket.
        """
        connection = self.active_connections[client_socket]
        data = connection.protocol.serialize(msg)
        length = len(data)
        client_socket.sendall(length.to_bytes(4, "big"))
        client_socket.sendall(data)

    def handle_list_accounts(self, client_socket: socket.socket, message: Message) -> None:
        pattern = message.payload.get("pattern", "")
        page = int(message.payload.get("page", 1))
        per_page = 10

        result = self.db.list_accounts(pattern, page, per_page)

        connection = self.active_connections[client_socket]
        response = Message(
            type=MessageType.SUCCESS,
            payload=result,  # e.g. { "users": [...], "total": X, ... }
            sender="SERVER",
            recipient=connection.username or "unknown",
            timestamp=time.time(),
        )
        self.send_message_to_socket(client_socket, response)

    def handle_read_messages(self, client_socket: socket.socket, message: Message) -> None:
        """
        This marks only the fetched messages as read. If you request offset=20, limit=20,
        you'll mark that chunk of older messages as read, effectively reading them
        'as the user scrolls.'
        """
        offset = int(message.payload.get("offset", 0))
        limit = int(message.payload.get("limit", 20))
        other_user = message.payload.get("otherUser")

        connection = self.active_connections[client_socket]
        username = connection.username
        if not username:
            self.send_response(client_socket, MessageType.ERROR, "Not logged in")
            return

        if other_user:
            result = self.db.get_messages_between_users(username, other_user, offset, limit)
        else:
            result = self.db.get_messages_for_user(username, offset, limit)

        msg_ids = [m["id"] for m in result["messages"]]
        if msg_ids:
            self.db.mark_messages_as_read(username, msg_ids)

        response = Message(
            type=MessageType.SUCCESS,
            payload=result,
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )
        self.send_message_to_socket(client_socket, response)

    def handle_delete_messages(self, client_socket: socket.socket, message: Message) -> None:
        connection = self.active_connections[client_socket]
        username = connection.username
        if not username:
            self.send_response(client_socket, MessageType.ERROR, "Not logged in")
            return

        message_ids = message.payload.get("message_ids", [])
        if not isinstance(message_ids, list):
            self.send_response(client_socket, MessageType.ERROR, "'message_ids' must be a list")
            return

        success = self.db.delete_messages(username, message_ids)
        if success:
            self.send_response(client_socket, MessageType.SUCCESS, "Messages deleted")
        else:
            self.send_response(client_socket, MessageType.ERROR, "Failed to delete messages")

    def handle_list_chat_partners(self, client_socket: socket.socket, message: Message) -> None:
        """
        Return both:
         - A list of usernames (strings)
         - A dictionary of {username: unread_count}.
        """
        connection = self.active_connections[client_socket]
        username = connection.username
        if not username:
            self.send_response(client_socket, MessageType.ERROR, "Not logged in")
            return

        partners = self.db.get_chat_partners(username)
        unread_map = {}
        for p in partners:
            # Assuming get_unread_between_users returns the number of unread messages
            unread_map[p] = self.db.get_unread_between_users(username, p)

        response = Message(
            type=MessageType.SUCCESS,
            payload={
                "chat_partners": partners,  # e.g. ["alice", "bob"]
                "unread_map": unread_map,  # e.g. {"alice": 3, "bob": 1}
            },
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )
        self.send_message_to_socket(client_socket, response)


if __name__ == "__main__":
    server = ChatServer()
    server.start()
