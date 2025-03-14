import argparse
import getpass
import queue
import socket
import sys
import threading
import time
from typing import List, Optional, Tuple

from src.protocols.base import Message, MessageType, Protocol
from src.protocols.binary_protocol import BinaryProtocol
from src.protocols.json_protocol import JsonProtocol


class ChatClient:
    """
    A client implementation for the chat system.
    """

    def __init__(
        self, username: str, protocol_type: str, host: str = "127.0.0.1", port: int = 54400
    ) -> None:
        """
        Initialize a new chat client.
        """
        self.host: str = host
        self.port: int = port
        self.username: str = username
        self.socket: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running: bool = False
        self.receive_thread: Optional[threading.Thread] = None
        self.logged_in: bool = False
        self.protocol: Protocol

        if protocol_type.upper().startswith("J"):
            self.protocol_byte = b"J"
            self.protocol = JsonProtocol()
        else:
            self.protocol_byte = b"B"
            self.protocol = BinaryProtocol()

        self.response_lock = threading.Lock()
        self.last_response: Optional[Message] = None
        self.incoming_messages_queue: queue.Queue[Message] = queue.Queue()

    def connect(self) -> bool:
        """
        Connect to the chat server and start the message receiving thread.
        """
        try:
            self.socket.connect((self.host, self.port))
            self.socket.sendall(self.protocol_byte)
            self.running = True
            self.receive_thread = threading.Thread(target=self.receive_messages, daemon=True)
            self.receive_thread.start()
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            return False

    def _send_message_no_response(self, message: Message) -> bool:
        """
        Send a message to the server without waiting for a response.
        """
        try:
            data = self.protocol.serialize(message)
            length = len(data)
            self.socket.sendall(length.to_bytes(4, "big"))
            self.socket.sendall(data)
            return True
        except Exception as e:
            print(f"Communication error: {e}")
            return False

    def _send_message_and_wait(self, message: Message, timeout: float = 10.0) -> Optional[Message]:
        """
        Send a message and wait for server response.
        """
        with self.response_lock:
            self.last_response = None

        ok = self._send_message_no_response(message)
        if not ok:
            return None

        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.response_lock:
                if self.last_response is not None:
                    response = self.last_response
                    self.last_response = None
                    return response
            time.sleep(0.05)

        print("Timed out waiting for server response.")
        return None

    def read_conversation_sync(
        self, other_user: str, offset: int = 0, limit: int = 20
    ) -> Optional[Message]:
        """
        Read messages from a conversation with another user.
        """
        msg = Message(
            type=MessageType.READ_MESSAGES,
            payload={
                "otherUser": other_user,
                "offset": offset,
                "limit": limit,
            },
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        return self._send_message_and_wait(msg, timeout=10.0)

    def list_accounts_sync(self, pattern: str = "", page: int = 1) -> Optional[Message]:
        """
        Request list of user accounts from server.
        """
        msg = Message(
            type=MessageType.LIST_ACCOUNTS,
            payload={"pattern": pattern, "page": page},
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self._send_message_and_wait(msg)
        return response

    def list_chat_partners_sync(self) -> Optional[Message]:
        """
        Request list of users this client has chatted with.
        """
        msg = Message(
            type=MessageType.LIST_CHAT_PARTNERS,
            payload={},
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        return self._send_message_and_wait(msg)

    def create_account(self, password: str) -> bool:
        """
        Create a new account on the server.
        """
        msg = Message(
            type=MessageType.CREATE_ACCOUNT,
            payload={"username": self.username, "password": password},
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        return self._send_message_no_response(msg)

    def login(self, password: str) -> bool:
        """
        Log in to an existing account.
        """
        msg = Message(
            type=MessageType.LOGIN,
            payload={"username": self.username, "password": password},
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        return self._send_message_no_response(msg)

    def login_sync(self, password: str, timeout: float = 10.0) -> Tuple[bool, Optional[str]]:
        """
        Log in to an existing account synchronously.
        """
        msg = Message(
            type=MessageType.LOGIN,
            payload={"username": self.username, "password": password},
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self._send_message_and_wait(msg, timeout=timeout)
        if response:
            if response.type == MessageType.SUCCESS:
                self.logged_in = True
                return True, None
            elif response.type == MessageType.ERROR:
                error_text = response.payload.get("text", "Unknown error.")
                return False, error_text
        return False, "No response from server."

    def delete_account(self, timeout: float = 10.0) -> bool:
        """
        Delete the current account from the server.
        Now waits for a response from the server.
        """
        if not self.logged_in:
            print("Must be logged in to delete account.")
            return False

        msg = Message(
            type=MessageType.DELETE_ACCOUNT,
            payload={},
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self._send_message_and_wait(msg, timeout=timeout)
        if response and response.type == MessageType.SUCCESS:
            return True
        else:
            print("Failed to delete account.")
            return False

    def send_message(self, recipient: str, text: str) -> bool:
        """
        Send a chat message to another user.
        """
        if not self.logged_in:
            print("Must be logged in to send messages.")
            return False

        msg = Message(
            type=MessageType.SEND_MESSAGE,
            payload={"text": text},
            sender=self.username,
            recipient=recipient,
            timestamp=time.time(),
        )
        return self._send_message_no_response(msg)

    def delete_messages_sync(self, message_ids: List[int], timeout: float = 10.0) -> bool:
        """
        Send a DELETE_MESSAGES request and wait for confirmation.
        """
        if not self.logged_in:
            print("Must be logged in to delete messages.")
            return False

        msg = Message(
            type=MessageType.DELETE_MESSAGES,
            payload={"message_ids": message_ids},
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self._send_message_and_wait(msg, timeout=timeout)
        if response and response.type == MessageType.SUCCESS:
            return True
        else:
            print("Failed to delete messages.")
            return False

    def receive_messages(self) -> None:
        """
        Continuously receive and process messages from the server.
        """
        while self.running:
            try:
                length_bytes = self.socket.recv(4)
                if not length_bytes:
                    print("Server closed connection.")
                    break

                msg_len = int.from_bytes(length_bytes, "big")

                message_data = b""
                while len(message_data) < msg_len:
                    chunk = self.socket.recv(msg_len - len(message_data))
                    if not chunk:
                        print("Server closed connection in the middle of a message.")
                        break
                    message_data += chunk

                if len(message_data) < msg_len:
                    break

                message = self.protocol.deserialize(message_data)
                text = message.payload.get("text", "")

                if message.type in [
                    MessageType.SUCCESS,
                    MessageType.ERROR,
                    MessageType.LIST_ACCOUNTS,
                    MessageType.READ_MESSAGES,
                    MessageType.DELETE_MESSAGES,
                    MessageType.LIST_CHAT_PARTNERS,
                ]:
                    with self.response_lock:
                        self.last_response = message

                if message.type == MessageType.SEND_MESSAGE:
                    if "id" not in message.payload:
                        print("Received SEND_MESSAGE without 'id'.")
                        continue
                    self.incoming_messages_queue.put(message)

                if message.type == MessageType.SUCCESS:
                    if ("Login successful" in text) or ("Account created" in text):
                        self.logged_in = True

            except Exception as e:
                print(f"Error in receive thread: {e}")
                break

        self.running = False
        self.close()

    def close(self) -> None:
        """
        Close the connection to the server and clean up resources.
        """
        self.running = False
        try:
            self.socket.close()
            print("Connection closed.")
        except Exception as e:
            print(f"Error closing connection: {e}")


def list_accounts(client: ChatClient, pattern: str = "", page: int = 1) -> None:
    msg = Message(
        type=MessageType.LIST_ACCOUNTS,
        payload={"pattern": pattern, "page": page},
        sender=client.username,
        recipient="SERVER",
        timestamp=time.time(),
    )
    client._send_message_no_response(msg)


def read_messages(client: ChatClient, offset: int = 0, limit: int = 10) -> None:
    msg = Message(
        type=MessageType.READ_MESSAGES,
        payload={"offset": offset, "limit": limit},
        sender=client.username,
        recipient="SERVER",
        timestamp=time.time(),
    )
    client._send_message_no_response(msg)


def delete_messages(client: ChatClient, message_ids: List[int]) -> None:
    msg = Message(
        type=MessageType.DELETE_MESSAGES,
        payload={"message_ids": message_ids},
        sender=client.username,
        recipient="SERVER",
        timestamp=time.time(),
    )
    client._send_message_no_response(msg)


def get_password(prompt: str) -> str:
    while True:
        password = getpass.getpass(prompt)
        if len(password) >= 6:
            return password
        print("Password must be at least 6 characters long")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple chat client.")
    parser.add_argument("username", help="Your chat username")
    parser.add_argument(
        "--protocol",
        choices=["B", "J"],
        default="B",
        help="Which protocol to use: B = Binary, J = JSON",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Server host to connect to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=54400,
        help="Server port to connect to (default: 54400)",
    )
    args = parser.parse_args()

    client = ChatClient(
        username=args.username, protocol_type=args.protocol, host=args.host, port=args.port
    )

    try:
        if client.connect():
            print(f"Welcome, {args.username}!")
            print("1. Create new account")
            print("2. Login to existing account")
            choice = input("Choose an option (1/2): ")

            if choice == "1":
                password = get_password("Create password: ")
                confirm = get_password("Confirm password: ")
                if password != confirm:
                    print("Passwords don't match")
                    sys.exit(1)
                client.create_account(password)
            elif choice == "2":
                password = get_password("Enter password: ")
                success, error = client.login_sync(password)
                if success:
                    print("Login successful.")
                else:
                    print(f"Login failed: {error}")
                    sys.exit(1)
            else:
                print("Invalid choice")
                sys.exit(1)

            print("\nCommands:")
            print("1. Send message: <recipient>,<message>")
            print("2. Delete messages: !delete")
            print("3. Delete account: !delete_account")
            print("Press Ctrl+C to quit")

            while True:
                msg_input = input()
                if not msg_input:
                    break

                if msg_input.strip().lower() == "!delete":
                    try:
                        ids_input = input("Enter message IDs to delete (comma-separated): ")
                        message_ids = [
                            int(id_.strip())
                            for id_ in ids_input.split(",")
                            if id_.strip().isdigit()
                        ]
                        if message_ids:
                            confirm = input(
                                "Are you sure you want to delete the selected messages? (yes/no): "
                            )
                            if confirm.lower() == "yes":
                                success = client.delete_messages_sync(message_ids)
                                if success:
                                    print("Deletion successful.")
                                else:
                                    print("Deletion failed.")
                            else:
                                print("Deletion canceled.")
                        else:
                            print("No valid message IDs provided.")
                    except Exception as e:
                        print(f"Invalid input: {e}")
                    continue

                if msg_input.strip().lower() == "!delete_account":
                    confirm = input("Are you sure you want to delete your account? (yes/no): ")
                    if confirm.lower() == "yes":
                        success = client.delete_account()
                        if success:
                            print("Account deletion request sent.")
                            break
                        else:
                            print("Failed to delete account.")
                    else:
                        print("Account deletion canceled.")
                    continue

                if "," not in msg_input:
                    print("Invalid format. Use: <recipient>,<message>")
                    continue

                recipient, text = msg_input.split(",", 1)
                client.send_message(recipient.strip(), text.strip())
        else:
            print("Could not connect to server.")
    except KeyboardInterrupt:
        print("\nClient interrupted (Ctrl+C)")
    finally:
        client.close()
