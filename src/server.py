import socket
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.database.db_manager import DatabaseManager
from src.protocols.base import Message, MessageType, Protocol
from src.protocols.binary_protocol import BinaryProtocol
from src.protocols.json_protocol import JsonProtocol


@dataclass
class User:
    """
    Represents a user in the chat system.

    Attributes:
        username (str): The unique username of the user
        password_hash (bytes): The hashed password of the user
        messages (List[Dict]): List of messages associated with the user
    """

    username: str
    password_hash: bytes
    messages: List[Dict]


@dataclass
class ClientConnection:
    """
    Represents an active client connection to the server.

    Attributes:
        socket (socket.socket): The socket connection to the client
        protocol (Protocol): The protocol (JSON or Binary) used for communication
        username (Optional[str]): The username of the authenticated user, if any
    """

    socket: socket.socket
    protocol: Protocol
    username: Optional[str] = None


class ChatServer:
    """
    A chat server that handles multiple client connections and message routing.

    The server supports both JSON and Binary protocols for communication and
    manages user authentication, message delivery, and persistent storage.
    """

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

    def send_response(
        self, client_socket: socket.socket, message_type: MessageType, content: str
    ) -> None:
        """
        Send a response message to a client.

        Args:
            client_socket (socket.socket): The socket to send the response to
            message_type (MessageType): The type of message (SUCCESS, ERROR, etc.)
            content (str): The message content to send

        Note:
            If sending fails, the client will be removed from active connections.
        """
        connection = self.active_connections.get(client_socket)
        if not connection:
            print(f"Attempted to send response to unknown client socket: {client_socket}")
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
        except Exception as e:
            print(f"Failed to send response to {connection.username}: {e}")
            self.remove_client(client_socket)

    def handle_create_account(self, client_socket: socket.socket, message: Message) -> None:
        """
        Handle account creation request from a client.

        Args:
            client_socket (socket.socket): The client's socket connection
            message (Message): The account creation message containing username and password

        Note:
            Sends a success response if account creation succeeds,
            error response if username exists or required fields are missing.
        """
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
        """
        Handle login request from a client.

        Args:
            client_socket (socket.socket): The client's socket connection
            message (Message): The login message containing username and password

        Note:
            On successful login:
            - Updates connection state
            - Delivers undelivered messages
            - Sends success response with unread message count
            On failure:
            - Sends error response
        """
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

            # Deliver any undelivered messages
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
        """
        Handle account deletion request from a client.

        Args:
            client_socket (socket.socket): The client's socket connection
            message (Message): The delete account message

        Note:
            User must be logged in to delete their account.
            On success, removes client from active connections.
        """
        connection = self.active_connections.get(client_socket)
        if not connection or not connection.username:
            self.send_response(client_socket, MessageType.ERROR, "Not logged in")
            return

        username = connection.username
        if self.db.delete_account(username):
            self.send_response(client_socket, MessageType.SUCCESS, "Account deleted successfully")
            self.remove_client(client_socket)
        else:
            self.send_response(client_socket, MessageType.ERROR, "Failed to delete account")

    def deliver_undelivered_messages(self, username: str) -> None:
        """
        Deliver stored undelivered messages to a user upon login.

        Args:
            username (str): The username to deliver messages to

        Note:
            Messages are marked as delivered after successful delivery.
            Failed deliveries result in client removal.
        """
        undelivered_messages = self.db.get_undelivered_messages(username)
        target_socket = self.username_to_socket.get(username)
        if not target_socket:
            print(f"No active socket found for user {username} to deliver messages.")
            return

        connection = self.active_connections.get(target_socket)
        if not connection:
            print(f"No active connection found for socket {target_socket} to deliver messages.")
            return

        for message in undelivered_messages:
            try:
                timestamp = float(message["timestamp"])
            except (ValueError, TypeError):
                timestamp = time.time()
            msg = Message(
                type=MessageType.SEND_MESSAGE,
                payload={"text": message["content"]},
                sender=message["from"],
                recipient=username,
                timestamp=timestamp,
            )

            try:
                data = connection.protocol.serialize(msg)
                length = len(data)
                target_socket.sendall(length.to_bytes(4, "big"))
                target_socket.sendall(data)
                self.db.mark_message_as_delivered(message["id"])  # Mark as delivered
            except Exception as e:
                print(f"Error delivering undelivered message to {username}: {e}")
                self.remove_client(target_socket)

    def send_direct_message(
        self, target_username: str, message_content: str, sender_username: str
    ) -> None:
        """
        Send a message from one user to another.

        Args:
            target_username (str): The recipient's username
            message_content (str): The message content to send
            sender_username (str): The sender's username

        Note:
            If recipient is online, delivers immediately.
            If offline, stores message for later delivery.
            Handles non-existent users and delivery failures.
        """
        if not self.db.user_exists(target_username):
            # Send error to sender
            sender_socket = self.username_to_socket.get(sender_username)
            if sender_socket:
                self.send_response(
                    sender_socket,
                    MessageType.ERROR,
                    f"User {target_username} does not exist",
                )
            else:
                print(f"Sender {sender_username} socket not found.")
            return

        # Check if the target user is online
        target_socket = self.username_to_socket.get(target_username)
        if target_socket:
            connection = self.active_connections.get(target_socket)
            if not connection:
                print(f"Connection not found for target user {target_username}.")
                self.send_response(
                    target_socket,
                    MessageType.ERROR,
                    f"User {target_username} is not available.",
                )
                return

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
                target_socket.sendall(length.to_bytes(4, "big"))
                target_socket.sendall(data)

                self.db.store_message(
                    sender_username, target_username, message_content, True
                )  # Store message and set delivered to True
                self.db.mark_message_as_delivered(
                    self.db.get_last_message_id(sender_username, target_username)
                )  # Mark message as delivered
            except Exception as e:
                print(f"Error sending to user {target_username}: {e}")
                self.remove_client(target_socket)
        else:
            # Store message as undelivered
            self.db.store_message(
                sender_username, target_username, message_content, False
            )  # Store message and set delivered to False
            print(f"User {target_username} is offline. Message stored as undelivered.")

    def handle_client(self, client_socket: socket.socket) -> None:
        """
        Handle all communication with a connected client.

        Args:
            client_socket (socket.socket): The client's socket connection

        Note:
            Runs in a separate thread for each client.
            Handles all message types and maintains client state.
            Removes client on any unhandled exceptions or disconnection.
        """
        connection = self.active_connections.get(client_socket)
        if not connection:
            print(f"No connection found for client socket: {client_socket}")
            return

        try:
            while True:
                length_bytes = self.receive_all(client_socket, 4)
                if not length_bytes:
                    print("Client disconnected.")
                    break

                message_length = int.from_bytes(length_bytes, "big")
                message_data = self.receive_all(client_socket, message_length)
                if not message_data:
                    print("Client disconnected during message reception.")
                    break

                if not connection:
                    print("Connection lost during message processing")
                    break

                message = connection.protocol.deserialize(message_data)

                # Handle different message types
                if message.type == MessageType.CREATE_ACCOUNT:
                    self.handle_create_account(client_socket, message)
                elif message.type == MessageType.LOGIN:
                    self.handle_login(client_socket, message)
                    # TODO(@ItamarRocha): Remove duplicated code
                    connection = self.active_connections.get(client_socket)  # re-acquire connection
                    username = connection.username if connection else ""
                    if username:
                        self.deliver_undelivered_messages(username)  # deliver messages
                elif message.type == MessageType.LIST_ACCOUNTS:
                    if not connection or not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in")
                        continue
                    self.handle_list_accounts(client_socket, message)
                elif message.type == MessageType.SEND_MESSAGE:
                    if not connection or not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in")
                        continue
                    recipient = message.recipient
                    if not recipient:
                        self.send_response(
                            client_socket, MessageType.ERROR, "No recipient specified"
                        )
                        continue
                    self.send_direct_message(
                        recipient, message.payload["text"], connection.username
                    )
                elif message.type == MessageType.READ_MESSAGES:
                    if not connection or not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in")
                        continue
                    self.handle_read_messages(client_socket, message)
                elif message.type == MessageType.DELETE_MESSAGES:
                    if not connection or not connection.username:
                        self.send_response(client_socket, MessageType.ERROR, "Not logged in")
                        continue
                    self.handle_delete_messages(client_socket, message)
                elif message.type == MessageType.DELETE_ACCOUNT:
                    self.handle_delete_account(client_socket, message)
                elif message.type == MessageType.LIST_CHAT_PARTNERS:
                    self.handle_list_chat_partners(client_socket, message)
                else:
                    self.send_response(client_socket, MessageType.ERROR, "Unknown message type")
        except Exception as e:
            print(f"Error handling client: {e}")
        finally:
            self.remove_client(client_socket)

    def receive_all(self, client_socket: socket.socket, length: int) -> Optional[bytes]:
        """
        Receive exactly the specified number of bytes from a socket.

        Args:
            client_socket (socket.socket): The socket to receive from
            length (int): The number of bytes to receive

        Returns:
            Optional[bytes]: The received data, or None if reception fails

        Note:
            Handles partial receives and connection errors.
        """
        data = b""
        while len(data) < length:
            try:
                chunk = client_socket.recv(length - len(data))
                if not chunk:
                    return None
                data += chunk
            except Exception as e:
                print(f"Error receiving data: {e}")
                return None
        return data

    def remove_client(self, client_socket: socket.socket) -> None:
        """
        Remove a client from active connections and clean up resources.

        Args:
            client_socket (socket.socket): The socket connection to remove

        Note:
            Thread-safe removal of client connections.
            Closes socket and updates server state.
        """
        with self.lock:
            connection = self.active_connections.pop(client_socket, None)
            if connection and connection.username:
                self.username_to_socket.pop(connection.username, None)
                print(f"User {connection.username} has been disconnected.")
            try:
                client_socket.close()
            except Exception as e:
                print(f"Error closing client socket: {e}")

    def start(self) -> None:
        """
        Start the server and listen for incoming connections.

        Note:
            Runs indefinitely until interrupted.
            Spawns a new thread for each client connection.
            Handles protocol negotiation for new connections.
        """
        self.socket.listen(5)
        print(f"Server started on {self.host}:{self.port}")

        while True:
            try:
                client_socket, address = self.socket.accept()
                print(f"New connection from {address}")

                # Receive protocol byte
                protocol_byte = self.receive_all(client_socket, 1)
                if not protocol_byte:
                    print(f"Failed to receive protocol byte from {address}. Closing connection.")
                    client_socket.close()
                    continue

                protocol = JsonProtocol() if protocol_byte == b"J" else BinaryProtocol()
                protocol_name = "JSON" if protocol_byte == b"J" else "Binary"

                connection = ClientConnection(socket=client_socket, protocol=protocol)
                print(f"Using {protocol_name} protocol for connection from {address}")

                with self.lock:
                    self.active_connections[client_socket] = connection

                thread = threading.Thread(target=self.handle_client, args=(client_socket,))
                thread.daemon = True
                thread.start()
            except KeyboardInterrupt:
                print("Server shutting down...")
                break
            except Exception as e:
                print(f"Error accepting new connection: {e}")

        self.shutdown()

    def send_message_to_socket(self, client_socket: socket.socket, msg: Message) -> None:
        """
        Serialize and send a Message object to a client socket.

        Args:
            client_socket (socket.socket): The socket to send to
            msg (Message): The message object to send

        Note:
            Handles serialization and length prefixing.
            Removes client on send failures.
        """
        connection = self.active_connections.get(client_socket)
        if not connection:
            print(f"No connection found for client socket: {client_socket}")
            return

        try:
            data = connection.protocol.serialize(msg)
            length = len(data)
            client_socket.sendall(length.to_bytes(4, "big"))
            client_socket.sendall(data)
        except Exception as e:
            print(f"Failed to send message to {connection.username}: {e}")
            self.remove_client(client_socket)

    def handle_list_accounts(self, client_socket: socket.socket, message: Message) -> None:
        """
        Handle request to list user accounts.

        Args:
            client_socket (socket.socket): The requesting client's socket
            message (Message): The list accounts request message

        Note:
            Supports pattern matching and pagination.
            Returns list of matching usernames.
        """
        pattern = message.payload.get("pattern", "")
        page = int(message.payload.get("page", 1))
        per_page = 10

        result = self.db.list_accounts(pattern, page, per_page)

        connection = self.active_connections.get(client_socket)
        if not connection:
            print(f"No connection found for client socket: {client_socket}")
            return

        response = Message(
            type=MessageType.SUCCESS,
            payload=result,  # e.g., { "users": [...], "total": X, ... }
            sender="SERVER",
            recipient=connection.username or "unknown",
            timestamp=time.time(),
        )
        self.send_message_to_socket(client_socket, response)

    def handle_read_messages(self, client_socket: socket.socket, message: Message) -> None:
        """
        Handle request to read messages.

        Args:
            client_socket (socket.socket): The requesting client's socket
            message (Message): The read messages request message

        Note:
            Supports reading messages between specific users.
            Marks retrieved messages as read.
            Handles pagination with offset and limit.
        """
        offset = int(message.payload.get("offset", 0))
        limit = int(message.payload.get("limit", 20))
        other_user = message.payload.get("otherUser")

        connection = self.active_connections.get(client_socket)
        if not connection:
            print(f"No connection found for client socket: {client_socket}")
            return

        username = connection.username
        if not username:
            self.send_response(client_socket, MessageType.ERROR, "Not logged in")
            return

        try:
            if other_user:
                result = self.db.get_messages_between_users(username, other_user, offset, limit)
            else:
                result = self.db.get_messages_for_user(username, offset, limit)

            msg_ids = [m["id"] for m in result.get("messages", [])]
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
        except Exception as e:
            print(f"Error reading messages: {e}")
            self.send_response(
                client_socket, MessageType.ERROR, f"Failed to read messages: {str(e)}"
            )

    def handle_delete_messages(self, client_socket: socket.socket, message: Message) -> None:
        """
        Handle request to delete messages.

        Args:
            client_socket (socket.socket): The requesting client's socket
            message (Message): The delete messages request message

        Note:
            Validates message IDs format.
            Only allows users to delete their own messages.
            Sends success/error response based on operation result.
        """
        connection = self.active_connections.get(client_socket)
        if not connection or not connection.username:
            self.send_response(client_socket, MessageType.ERROR, "Not logged in")
            return

        message_ids = message.payload.get("message_ids", [])
        if not isinstance(message_ids, list):
            self.send_response(client_socket, MessageType.ERROR, "'message_ids' must be a list")
            return

        try:
            success = self.db.delete_messages(connection.username, message_ids)
            if success:
                self.send_response(client_socket, MessageType.SUCCESS, "Messages deleted")
            else:
                self.send_response(client_socket, MessageType.ERROR, "Failed to delete messages")
        except Exception as e:
            print(f"Error deleting messages: {e}")
            self.send_response(
                client_socket, MessageType.ERROR, f"Failed to delete messages: {str(e)}"
            )

    def handle_list_chat_partners(self, client_socket: socket.socket, message: Message) -> None:
        """
        Handle request to list chat partners.

        Args:
            client_socket (socket.socket): The requesting client's socket
            message (Message): The list chat partners request message

        Note:
            Returns list of users the client has chatted with.
            Includes unread message counts for each chat partner.
            Requires user to be logged in.
        """
        connection = self.active_connections.get(client_socket)
        if not connection or not connection.username:
            self.send_response(client_socket, MessageType.ERROR, "Not logged in")
            return

        username = connection.username
        try:
            partners = self.db.get_chat_partners(username)
            unread_map = {}
            for p in partners:
                # Assuming get_unread_between_users returns the number of unread messages
                unread_map[p] = self.db.get_unread_between_users(username, p)

            response = Message(
                type=MessageType.SUCCESS,
                payload={
                    "chat_partners": partners,  # e.g., ["alice", "bob"]
                    "unread_map": unread_map,  # e.g., {"alice": 3, "bob": 1}
                },
                sender="SERVER",
                recipient=username,
                timestamp=time.time(),
            )
            self.send_message_to_socket(client_socket, response)
        except Exception as e:
            print(f"Error listing chat partners: {e}")
            self.send_response(
                client_socket, MessageType.ERROR, f"Failed to list chat partners: {str(e)}"
            )

    def shutdown(self) -> None:
        """
        Gracefully shut down the server.

        Note:
            Closes all client connections.
            Cleans up server resources.
            Thread-safe shutdown process.
        """
        print("Shutting down server...")
        with self.lock:
            for client_socket in list(self.active_connections.keys()):
                try:
                    client_socket.close()
                except Exception as e:
                    print(f"Error closing client socket: {e}")
            self.active_connections.clear()
            self.username_to_socket.clear()
        try:
            self.socket.close()
        except Exception as e:
            print(f"Error closing server socket: {e}")
        print("Server shutdown complete.")


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
        print("\nKeyboard interrupt received. Exiting...")
    finally:
        server.shutdown()
