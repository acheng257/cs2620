import socket
from typing import Dict, Set, List, Optional
import threading
from dataclasses import dataclass
from protocols.binary_protocol import BinaryProtocol
from protocols.base import MessageType, Protocol, Message


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
    def __init__(self, host="127.0.0.1", port=54400):
        self.host = host
        self.port = port
        self.active_connections: Dict[socket.socket, ClientConnection] = {}
        self.username_to_socket: Dict[str, socket.socket] = (
            {}
        )  # Map usernames to sockets
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))
        self.lock = threading.Lock()

    def send_direct_message(
        self, target_username: str, message_content: str, sender_username: str
    ):
        """Send a message to a specific client using the binary protocol."""
        with self.lock:
            if target_username in self.username_to_socket:
                target_socket = self.username_to_socket[target_username]
                connection = self.active_connections[target_socket]

                # Create a Message object
                message = Message(
                    type=MessageType.SEND_MESSAGE,
                    payload={"text": message_content},
                    sender=sender_username,
                    recipient=target_username,
                )

                try:
                    data = connection.protocol.serialize(message)  # serialize message
                    length = len(data)
                    target_socket.send(length.to_bytes(4, "big"))  # send length
                    target_socket.send(data)  # send message
                except Exception as e:
                    print(f"Error sending to user {target_username}: {e}")
                    self.remove_client(target_socket)
            else:
                # if target client doesn't exist, send error back to sender
                sender_socket = self.username_to_socket[sender_username]
                connection = self.active_connections[sender_socket]

                try:
                    error_message = Message(
                        type=MessageType.SEND_MESSAGE,
                        payload={"text": f"Error: User {target_username} not found"},
                        sender="SERVER", # server is sender for errors
                        recipient=sender_username
                    )
                    data = connection.protocol.serialize(error_message)
                    length = len(data)
                    sender_socket.send(length.to_bytes(4, "big"))
                    sender_socket.send(data)

                except Exception as e:
                    print(f"Error sending error message to user {sender_username}: {e}")
                    self.remove_client(sender_socket)

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

            protocol_byte = client_socket.recv(1)
            # TODO: uncomment this line once JsonProtocol exists
            # protocol = JsonProtocol() if protocol_byte == b"J" else BinaryProtocol()
            protocol = BinaryProtocol()

            connection = ClientConnection(socket=client_socket, protocol=protocol)
            with self.lock:
                self.active_connections[client_socket] = connection

            thread = threading.Thread(target=self.handle_client, args=(client_socket,))
            thread.daemon = True
            thread.start()

    def handle_client(self, client_socket):
        connection = self.active_connections[client_socket]
        try:
            while True:
                length_bytes = client_socket.recv(4)
                if not length_bytes:
                    print("Client disconnected.")
                    break

                message_length = int.from_bytes(length_bytes, 'big')
                
                message_data = b''
                # recv message data in chunks since messages may not be sent all at once
                while len(message_data) < message_length:
                    chunk = client_socket.recv(message_length - len(message_data))
                    if not chunk:
                        print("Client disconnected during message reception.")
                        break
                    message_data += chunk

                if len(message_data) < message_length:
                    break

                message_content = connection.protocol.deserialize(message_data)

                target_username = message_content.recipient
                content = message_content.payload

                if self.active_connections[client_socket].username is None:
                    username = message_content.sender
                    self.active_connections[client_socket].username = username
                    with self.lock:
                        self.username_to_socket[username] = client_socket
                    print(f"User {username} registered")
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