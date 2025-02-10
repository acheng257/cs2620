import socket
from typing import Dict, Set, List, Optional
import threading
from dataclasses import dataclass
from protocols.base import Protocol, Message
from protocols.binary_protocol import BinaryProtocol

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

        self.users: Dict[str, User] = {}
        self.active_connections: Dict[socket.socket, ClientConnection] = {}
        self.user_sockets: Dict[str, Set[socket.socket]] = {}

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))

    def start(self):
        """Start the server."""
        self.socket.listen(5)
        print(f"Server started on {self.host}:{self.port}")

        while True:
            client_socket, address = self.socket.accept()
            print(f"New connection from {address}")

            protocol_byte = client_socket.recv(1)
            protocol = BinaryProtocol()

            connection = ClientConnection(socket=client_socket, protocol=protocol)
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
                    # Connection closed by client
                    print("Client disconnected.")
                    break

                message_length = int.from_bytes(length_bytes, "big")
                message_data = client_socket.recv(message_length)

                if not message_data:
                    print("Client disconnected.")
                    break

                message = connection.protocol.deserialize(message_data)
                self.handle_message(client_socket, message)
                
        except Exception as e:
            print(f"Error handling client: {e}")

    def handle_message(self, client_socket: socket.socket, message: Message):
        """Handle received message."""
        connection = self.active_connections[client_socket]
        print("Message received from client:", message)

if __name__ == "__main__":
    server = ChatServer()
    server.start()