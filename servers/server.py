import socket
from typing import Dict, Set, List, Optional
import threading
from dataclasses import dataclass
from protocols.base import Protocol
import sqlite3


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
    def __init__(self, host="127.0.0.1", port=54400, db_path="chat.db"):
        self.host = host
        self.port = port
        self.db_path = db_path
        self.active_connections: Dict[socket.socket, ClientConnection] = {}
        self.username_to_socket: Dict[str, socket.socket] = {}
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))
        self.lock = threading.Lock()
        self.init_database()

    def init_database(self):
        """Initialize the SQLite database and create necessary tables."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Create messages table
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender TEXT NOT NULL,
                        recipient TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """
                )
                conn.commit()
        except Exception as e:
            print(f"Error initializing database: {e}")

    def store_message(self, sender: str, recipient: str, content: str):
        """Store a message in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO messages (sender, recipient, content)
                    VALUES (?, ?, ?)
                """,
                    (sender, recipient, content),
                )
                conn.commit()
        except Exception as e:
            print(f"Error storing message in database: {e}")

    def get_chat_history(self, user1: str, user2: str, limit: int = 50) -> List[tuple]:
        """Retrieve chat history between two users."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT sender, recipient, content, timestamp
                    FROM messages
                    WHERE (sender = ? AND recipient = ?)
                    OR (sender = ? AND recipient = ?)
                    ORDER BY timestamp DESC
                    LIMIT ?
                """,
                    (user1, user2, user2, user1, limit),
                )
                return cursor.fetchall()
        except Exception as e:
            print(f"Error retrieving chat history: {e}")
            return []

    def send_direct_message(
        self, target_username: str, message: str, sender_username: str
    ):
        """Send a message to a specific client."""
        with self.lock:
            if target_username in self.username_to_socket:
                target_socket = self.username_to_socket[target_username]
                try:
                    formatted_message = f"{message},{sender_username}"
                    target_socket.send(formatted_message.encode("utf-8"))
                    # Store message in database
                    self.store_message(sender_username, target_username, message)
                except Exception as e:
                    print(f"Error sending to user {target_username}: {e}")
                    self.remove_client(target_socket)
            else:
                # If target client doesn't exist, send error back to sender
                sender_socket = self.username_to_socket[sender_username]
                try:
                    error_msg = f"Error: User {target_username} not found,SERVER"
                    sender_socket.send(error_msg.encode("utf-8"))
                except Exception as e:
                    print(f"Error sending error message to user {sender_username}: {e}")

    def send_chat_history(self, username: str, other_username: str):
        """Send chat history to a user."""
        if username in self.username_to_socket:
            history = self.get_chat_history(username, other_username)
            if history:
                formatted_history = "Chat history:\\n"
                for sender, recipient, content, timestamp in history:
                    formatted_history += f"[{timestamp}] {sender}: {content}\\n"
                self.username_to_socket[username].send(
                    f"{formatted_history},SERVER".encode("utf-8")
                )

    def remove_client(self, client_socket: socket.socket):
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

    def start(self):
        """Start the server."""
        self.socket.listen(5)
        print(f"Server started on {self.host}:{self.port}")

        while True:
            client_socket, address = self.socket.accept()
            print(f"New connection from {address}")

            connection = ClientConnection(socket=client_socket, protocol=None)
            with self.lock:
                self.active_connections[client_socket] = connection

            thread = threading.Thread(target=self.handle_client, args=(client_socket,))
            thread.daemon = True
            thread.start()

    def handle_client(self, client_socket):
        try:
            while True:
                data = client_socket.recv(1024)
                if not data:
                    print("Client disconnected.")
                    break

                message = data.decode("utf-8")
                target_username, content = message.split(",", 1)

                # Set username if not already set
                if self.active_connections[client_socket].username is None:
                    username = target_username
                    self.active_connections[client_socket].username = username
                    with self.lock:
                        self.username_to_socket[username] = client_socket
                    print(f"User {username} registered")
                    continue

                # Check if this is a history request
                # TODO(@ItamarRocha): Remove this and change just for the client initialization
                if content.strip().lower() == "!history":
                    self.send_chat_history(
                        self.active_connections[client_socket].username, target_username
                    )
                    continue

                sender_username = self.active_connections[client_socket].username
                print(f"User {sender_username} sent to {target_username}: {content}")
                self.send_direct_message(target_username, content, sender_username)

        except Exception as e:
            print(f"Error handling client: {e}")
        finally:
            self.remove_client(client_socket)


if __name__ == "__main__":
    server = ChatServer()
    server.start()
