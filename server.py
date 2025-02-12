# server.py

import socket
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from protocols.base import Message, MessageType, Protocol
from protocols.binary_protocol import BinaryProtocol
from protocols.json_protocol import JsonProtocol
from src.database.db_manager import DatabaseManager  # Adjusted import path


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
    def __init__(self, host: str = "0.0.0.0", port: int = 54400, db_path: str = "chat.db") -> None:
        """
        Initialize the ChatServer.

        Args:
            host (str): The hostname or IP address to bind the server to.
                        "0.0.0.0" binds to all available interfaces.
            port (int): The port number to listen on.
            db_path (str): Path to the database file.
        """
        self.host = host
        self.port = port
        self.active_connections: Dict[socket.socket, ClientConnection] = {}
        self.username_to_socket: Dict[str, socket.socket] = {}
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))
        self.lock = threading.Lock()
        self.db = DatabaseManager(db_path)
        print(f"[INFO] ChatServer initialized on {self.host}:{self.port}")

    def send_response(
        self, client_socket: socket.socket, message_type: MessageType, content: str
    ) -> None:
        """Send a response message to a client."""
        connection = self.active_connections.get(client_socket)
        if not connection:
            print(f"[ERROR] Attempted to send response to unknown client socket: {client_socket}")
            return

        response = Message(
            type=message_type,
            payload={"text": content},
            sender="SERVER",
            recipient=connection.username or "unknown",
            timestamp=time.time(),
        )
        data = connection.protocol.serialize(response)
        try:
            length = len(data)
            client_socket.sendall(length.to_bytes(4, "big"))
            client_socket.sendall(data)
            print(f"[INFO] Sent {message_type.name} response to {connection.username or 'unknown'}.")
        except Exception as e:
            print(f"[ERROR] Failed to send response to {connection.username or 'unknown'}: {e}")
            self.remove_client(client_socket)

    def send_message_to_socket(self, client_socket: socket.socket, msg: Message) -> None:
        """
        A helper to serialize and send the given Message object
        to the specified client socket.
        """
        connection = self.active_connections.get(client_socket)
        if not connection:
            print(f"[ERROR] No connection found for client socket: {client_socket}")
            return

        try:
            data = connection.protocol.serialize(msg)
            length = len(data)
            client_socket.sendall(length.to_bytes(4, "big"))
            client_socket.sendall(data)
            print(f"[INFO] Sent {msg.type.name} message to {connection.username or 'unknown'}.")
        except Exception as e:
            print(f"[ERROR] Failed to send message to {connection.username or 'unknown'}: {e}")
            self.remove_client(client_socket)

    def handle_create_account(self, client_socket: socket.socket, message: Message) -> None:
        """Handle account creation request."""
        username = message.payload.get("username")
        password = message.payload.get("password")

        if not username or not password:
            self.send_response(client_socket, MessageType.ERROR, "Username and password required.")
            return

        if self.db.create_account(username, password):
            with self.lock:
                connection = self.active_connections.get(client_socket)
                if connection:
                    connection.username = username
                    self.username_to_socket[username] = client_socket
            self.send_response(client_socket, MessageType.SUCCESS, "Account created successfully.")
            print(f"[INFO] Account created for user: {username}")
        else:
            self.send_response(client_socket, MessageType.ERROR, "Username already exists.")
            print(f"[WARNING] Attempt to create duplicate account: {username}")

    def handle_login(self, client_socket: socket.socket, message: Message) -> None:
        """Handle login request."""
        username = message.payload.get("username")
        password = message.payload.get("password")

        if not username or not password:
            self.send_response(client_socket, MessageType.ERROR, "Username and password required.")
            return

        if self.db.verify_login(username, password):
            with self.lock:
                connection = self.active_connections.get(client_socket)
                if connection:
                    connection.username = username
                    self.username_to_socket[username] = client_socket

            # Send login success before delivering messages to ensure prompt response
            unread_count = self.db.get_unread_message_count(username)
            self.send_response(
                client_socket,
                MessageType.SUCCESS,
                f"Login successful. You have {unread_count} unread messages.",
            )
            print(f"[INFO] User '{username}' logged in successfully.")

            # Deliver any undelivered messages
            self.deliver_undelivered_messages(username)
        else:
            self.send_response(client_socket, MessageType.ERROR, "Invalid username or password.")
            print(f"[WARNING] Failed login attempt for user: {username}")

    def handle_delete_account(self, client_socket: socket.socket, message: Message) -> None:
        """Handle account deletion request."""
        connection = self.active_connections.get(client_socket)
        if not connection or not connection.username:
            self.send_response(client_socket, MessageType.ERROR, "Not logged in.")
            return

        username = connection.username
        if self.db.delete_account(username):
            self.send_response(client_socket, MessageType.SUCCESS, "Account deleted successfully.")
            print(f"[INFO] Account deleted for user: {username}")
            self.remove_client(client_socket)
        else:
            self.send_response(client_socket, MessageType.ERROR, "Failed to delete account.")
            print(f"[ERROR] Failed to delete account for user: {username}")

    def deliver_undelivered_messages(self, username: str) -> None:
        """Deliver undelivered messages to a user upon login."""
        undelivered_messages = self.db.get_undelivered_messages(username)
        target_socket = self.username_to_socket.get(username)
        if not target_socket:
            print(f"[ERROR] No active socket found for user {username} to deliver messages.")
            return

        connection = self.active_connections.get(target_socket)
        if not connection:
            print(f"[ERROR] No active connection found for socket {target_socket} to deliver messages.")
            return

        for message in undelivered_messages:
            try:
                timestamp = float(message["timestamp"])
            except (ValueError, TypeError):
                timestamp = time.time()
            msg = Message(
                type=MessageType.SEND_MESSAGE,
                payload={"text": message["content"], "id": message["id"]},  # Include message ID
                sender=message["from"],
                recipient=username,
                timestamp=timestamp,
            )

            try:
                self.send_message_to_socket(target_socket, msg)
                self.db.mark_message_as_delivered(message["id"])  # Mark as delivered
                print(f"[INFO] Delivered undelivered message ID {message['id']} to {username}.")
            except Exception as e:
                print(f"[ERROR] Error delivering undelivered message to {username}: {e}")
                self.remove_client(target_socket)

    def send_direct_message(
        self, target_username: str, message_content: str, sender_username: str
    ) -> None:
        """Send a message to a specific client using the protocol."""
        if not self.db.user_exists(target_username):
            # Send error to sender
            sender_socket = self.username_to_socket.get(sender_username)
            if sender_socket:
                self.send_response(
                    sender_socket,
                    MessageType.ERROR,
                    f"User '{target_username}' does not exist.",
                )
            else:
                print(f"[ERROR] Sender '{sender_username}' socket not found.")
            return

        # Check if the target user is online
        target_socket = self.username_to_socket.get(target_username)
        if target_socket:
            connection = self.active_connections.get(target_socket)
            if not connection:
                print(f"[ERROR] Connection not found for target user '{target_username}'.")
                self.send_response(
                    target_socket,
                    MessageType.ERROR,
                    f"User '{target_username}' is not available.",
                )
                return

            message_id = self.db.store_message(
                sender_username, target_username, message_content, True
            )  # Store message and set delivered to True

            if not message_id:
                self.send_response(
                    target_socket,
                    MessageType.ERROR,
                    "Failed to store the message.",
                )
                return

            message = Message(
                type=MessageType.SEND_MESSAGE,
                payload={"text": message_content, "id": message_id},
                sender=sender_username,
                recipient=target_username,
                timestamp=time.time(),
            )

            try:
                self.send_message_to_socket(target_socket, message)
                print(f"[INFO] Sent message from '{sender_username}' to '{target_username}'.")
            except Exception as e:
                print(f"[ERROR] Error sending message to '{target_username}': {e}")
                self.remove_client(target_socket)
        else:
            # Store message as undelivered
            message_id = self.db.store_message(
                sender_username, target_username, message_content, False
            )  # Store message and set delivered to False
            if message_id:
                print(f"[INFO] User '{target_username}' is offline. Message ID {message_id} stored as undelivered.")
            else:
                print(f"[ERROR] Failed to store undelivered message for '{target_username}'.")

    def handle_client(self, client_socket: socket.socket) -> None:
        """Handle communication with a connected client."""
        connection = self.active_connections.get(client_socket)
        if not connection:
            print(f"[ERROR] No connection found for client socket: {client_socket}")
            return

        try:
            while True:
                length_bytes = self.receive_all(client_socket, 4)
                if not length_bytes:
                    print(f"[INFO] Client '{connection.username or 'unknown'}' disconnected.")
                    break

                message_length = int.from_bytes(length_bytes, "big")
                message_data = self.receive_all(client_socket, message_length)
                if not message_data:
                    print(f"[INFO] Client '{connection.username or 'unknown'}' disconnected during message reception.")
                    break

                message = connection.protocol.deserialize(message_data)
                print(f"[RECEIVED] {connection.username or 'unknown'} sent {message.type.name} with payload: {message.payload}")

                if message.type == MessageType.CREATE_ACCOUNT:
                    self.handle_create_account(client_socket, message)
                elif message.type == MessageType.LOGIN:
                    self.handle_login(client_socket, message)
                elif message.type == MessageType.DELETE_ACCOUNT:
                    self.handle_delete_account(client_socket, message)
                elif message.type == MessageType.SEND_MESSAGE:
                    if not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in.")
                        continue
                    recipient = message.recipient
                    if not recipient:
                        self.send_response(
                            client_socket, MessageType.ERROR, "No recipient specified."
                        )
                        continue
                    self.send_direct_message(
                        recipient, message.payload.get("text", ""), connection.username
                    )
                elif message.type == MessageType.LIST_ACCOUNTS:
                    if not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in.")
                        continue
                    self.handle_list_accounts(client_socket, message)
                elif message.type == MessageType.READ_MESSAGES:
                    if not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in.")
                        continue
                    self.handle_read_messages(client_socket, message)
                elif message.type == MessageType.DELETE_MESSAGES:
                    if not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in.")
                        continue
                    self.handle_delete_messages(client_socket, message)
                elif message.type == MessageType.LIST_CHAT_PARTNERS:
                    if not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in.")
                        continue
                    self.handle_list_chat_partners(client_socket, message)
                else:
                    self.send_response(client_socket, MessageType.ERROR, "Unknown message type.")
                    print(f"[WARNING] Received unknown message type from {connection.username or 'unknown'}: {message.type}")
        except Exception as e:
            print(f"[ERROR] Error handling client '{connection.username or 'unknown'}': {e}")
        finally:
            self.remove_client(client_socket)

    def handle_list_accounts(self, client_socket: socket.socket, message: Message) -> None:
        """Handle LIST_ACCOUNTS request."""
        pattern = message.payload.get("pattern", "")
        page = int(message.payload.get("page", 1))
        per_page = 10  # Define how many accounts to list per page

        result = self.db.list_accounts(pattern, page, per_page)

        connection = self.active_connections.get(client_socket)
        if not connection:
            print(f"[ERROR] No connection found for client socket: {client_socket}")
            return

        response = Message(
            type=MessageType.SUCCESS,
            payload=result,  # e.g., { "users": [...], "total": X, ... }
            sender="SERVER",
            recipient=connection.username or "unknown",
            timestamp=time.time(),
        )
        self.send_message_to_socket(client_socket, response)
        print(f"[INFO] Sent LIST_ACCOUNTS response to {connection.username or 'unknown'}.")

    def handle_read_messages(self, client_socket: socket.socket, message: Message) -> None:
        """
        Handle READ_MESSAGES request.
        Marks fetched messages as read.
        """
        offset = int(message.payload.get("offset", 0))
        limit = int(message.payload.get("limit", 20))
        other_user = message.payload.get("otherUser")

        connection = self.active_connections.get(client_socket)
        if not connection:
            print(f"[ERROR] No connection found for client socket: {client_socket}")
            return

        username = connection.username
        if not username:
            self.send_response(client_socket, MessageType.ERROR, "Not logged in.")
            return

        if other_user:
            result = self.db.get_messages_between_users(username, other_user, offset, limit)
        else:
            result = self.db.get_messages_for_user(username, offset, limit)

        msg_ids = [m["id"] for m in result.get("messages", [])]
        if msg_ids:
            self.db.mark_messages_as_read(username, msg_ids)
            print(f"[INFO] Marked messages as read for user '{username}'. Message IDs: {msg_ids}")

        response = Message(
            type=MessageType.SUCCESS,
            payload=result,
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )
        self.send_message_to_socket(client_socket, response)
        print(f"[INFO] Sent READ_MESSAGES response to {username}.")

    def handle_delete_messages(self, client_socket: socket.socket, message: Message) -> None:
        """Handle DELETE_MESSAGES request."""
        connection = self.active_connections.get(client_socket)
        if not connection or not connection.username:
            self.send_response(client_socket, MessageType.ERROR, "Not logged in.")
            return

        message_ids = message.payload.get("message_ids", [])
        if not isinstance(message_ids, list):
            self.send_response(client_socket, MessageType.ERROR, "'message_ids' must be a list.")
            print(f"[WARNING] Invalid 'message_ids' format from user '{connection.username}'.")
            return

        success = self.db.delete_messages(connection.username, message_ids)

        if success:
            self.send_response(client_socket, MessageType.SUCCESS, "Messages deleted for you.")
            print(f"[INFO] Deleted messages for user '{connection.username}'. Message IDs: {message_ids}")
        else:
            self.send_response(client_socket, MessageType.ERROR, "Failed to delete messages.")
            print(f"[ERROR] Failed to delete messages for user '{connection.username}'. Message IDs: {message_ids}")

    def handle_list_chat_partners(self, client_socket: socket.socket, message: Message) -> None:
        """
        Handle LIST_CHAT_PARTNERS request.
        Returns a list of chat partners and their unread message counts.
        """
        connection = self.active_connections.get(client_socket)
        if not connection or not connection.username:
            self.send_response(client_socket, MessageType.ERROR, "Not logged in.")
            return

        username = connection.username
        partners = self.db.get_chat_partners(username)
        unread_map = {}
        for p in partners:
            # Assuming get_unread_between_users returns the number of unread messages
            unread_map[p] = self.db.get_unread_between_users(username, p)

        response = Message(
            type=MessageType.SUCCESS,
            payload={
                "chat_partners": partners,  # e.g., ["alice", "bob"]
                "unread_map": unread_map,    # e.g., {"alice": 3, "bob": 1}
            },
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )
        self.send_message_to_socket(client_socket, response)
        print(f"[INFO] Sent LIST_CHAT_PARTNERS response to {username}.")

    def receive_all(self, client_socket: socket.socket, length: int) -> Optional[bytes]:
        """Helper function to receive exactly `length` bytes from the socket."""
        data = b""
        while len(data) < length:
            try:
                chunk = client_socket.recv(length - len(data))
                if not chunk:
                    return None
                data += chunk
            except Exception as e:
                connection = self.active_connections.get(client_socket)
                username = connection.username if connection else "unknown"
                print(f"[ERROR] Error receiving data from '{username}': {e}")
                return None
        return data

    def remove_client(self, client_socket: socket.socket) -> None:
        """Remove a client from active connections."""
        with self.lock:
            connection = self.active_connections.pop(client_socket, None)
            if connection and connection.username:
                self.username_to_socket.pop(connection.username, None)
                print(f"[INFO] User '{connection.username}' has been disconnected.")
            try:
                client_socket.close()
                print(f"[INFO] Closed connection socket: {client_socket}")
            except Exception as e:
                print(f"[ERROR] Error closing client socket: {e}")

    def start(self) -> None:
        """Start the server and listen for incoming connections."""
        self.socket.listen(5)
        print(f"[INFO] Server started on {self.host}:{self.port}")

        while True:
            try:
                client_socket, address = self.socket.accept()
                print(f"[INFO] New connection from {address}")

                # Receive protocol byte
                protocol_byte = self.receive_all(client_socket, 1)
                if not protocol_byte:
                    print(f"[WARNING] Failed to receive protocol byte from {address}. Closing connection.")
                    client_socket.close()
                    continue

                protocol = JsonProtocol() if protocol_byte == b"J" else BinaryProtocol()
                protocol_name = "JSON" if protocol_byte == b"J" else "Binary"

                connection = ClientConnection(socket=client_socket, protocol=protocol)
                print(f"[INFO] Using {protocol_name} protocol for connection from {address}")

                with self.lock:
                    self.active_connections[client_socket] = connection

                thread = threading.Thread(target=self.handle_client, args=(client_socket,))
                thread.daemon = True
                thread.start()
                print(f"[INFO] Started thread to handle client {address}")
            except KeyboardInterrupt:
                print("\n[INFO] Keyboard interrupt received. Shutting down server...")
                break
            except Exception as e:
                print(f"[ERROR] Error accepting new connection: {e}")

        self.shutdown()

    def shutdown(self) -> None:
        """Gracefully shut down the server and close all connections."""
        print("[INFO] Shutting down server...")
        with self.lock:
            for client_socket in list(self.active_connections.keys()):
                try:
                    client_socket.shutdown(socket.SHUT_RDWR)
                except Exception as e:
                    print(f"[ERROR] Error shutting down client socket: {e}")
                try:
                    client_socket.close()
                    print(f"[INFO] Closed connection socket: {client_socket}")
                except Exception as e:
                    print(f"[ERROR] Error closing client socket: {e}")
            self.active_connections.clear()
            self.username_to_socket.clear()
        try:
            self.socket.close()
            print("[INFO] Server socket closed.")
        except Exception as e:
            print(f"[ERROR] Error closing server socket: {e}")
        print("[INFO] Server shutdown complete.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Secure Chat Server")
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind the server to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=54400,
        help="Port to bind the server to (default: 54400)",
    )
    parser.add_argument(
        "--db_path",
        type=str,
        default="chat.db",
        help="Path to the database file (default: chat.db)",
    )
    args = parser.parse_args()

    server = ChatServer(host=args.host, port=args.port, db_path=args.db_path)
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[INFO] Keyboard interrupt received. Exiting...")
    finally:
        server.shutdown()
