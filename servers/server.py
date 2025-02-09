import socket
from typing import Dict, Set, List, Optional
import threading
from dataclasses import dataclass
from protocols.base import Protocol

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

            connection = ClientConnection(socket=client_socket, protocol="json")
            self.active_connections[client_socket] = connection

            thread = threading.Thread(target=self.handle_client, args=(client_socket,))
            thread.daemon = True
            thread.start()
    
    def handle_client(self, client_socket):
        try:
            while True:
                client_message = client_socket.recv(1024).decode('utf-8')
                if not client_message:
                    # Connection closed by client
                    print("Client disconnected.")
                    break
                print(client_message)
                clientId, message = client_message.split(",")
                print(f"Client {clientId} sent: {message}")
                
        except Exception as e:
            print(f"Error handling client: {e}")

if __name__ == "__main__":
    server = ChatServer()
    server.start()