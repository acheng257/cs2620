import argparse
import getpass
import socket
import sys
import threading
import time
from typing import Optional

from protocols.base import Message, MessageType, Protocol
from protocols.binary_protocol import BinaryProtocol
from protocols.json_protocol import JsonProtocol


class ChatClient:
    def __init__(
        self, username: str, protocol_type: str, host: str = "127.0.0.1", port: int = 54400
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = False
        self.receive_thread: Optional[threading.Thread] = None
        self.logged_in = False
        self.protocol: Protocol

        if protocol_type.upper().startswith("J"):
            self.protocol_byte = b"J"
            self.protocol = JsonProtocol()
        else:
            self.protocol_byte = b"B"
            self.protocol = BinaryProtocol()

    def connect(self) -> bool:
        try:
            self.socket.connect((self.host, self.port))
            self.socket.sendall(self.protocol_byte)
            self.running = True

            # Start thread that continuously reads incoming messages
            self.receive_thread = threading.Thread(target=self.receive_messages, daemon=True)
            self.receive_thread.start()

            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            return False

    def _send_message_no_response(self, message: Message) -> bool:
        """Send a message without expecting an immediate response."""
        try:
            data = self.protocol.serialize(message)
            length = len(data)
            self.socket.sendall(length.to_bytes(4, "big"))
            self.socket.sendall(data)
            return True
        except Exception as e:
            print(f"Communication error: {e}")
            return False

    def create_account(self, password: str) -> bool:
        """Create a new account."""
        message = Message(
            type=MessageType.CREATE_ACCOUNT,
            payload={"username": self.username, "password": password},
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        return self._send_message_no_response(message)

    def login(self, password: str) -> bool:
        """Log in to an existing account."""
        message = Message(
            type=MessageType.LOGIN,
            payload={"username": self.username, "password": password},
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        return self._send_message_no_response(message)

    def delete_account(self) -> bool:
        """Delete the current account."""
        if not self.logged_in:
            print("Must be logged in to delete account")
            return False

        message = Message(
            type=MessageType.DELETE_ACCOUNT,
            payload={},
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        return self._send_message_no_response(message)

    def send_message(self, recipient: str, text: str) -> bool:
        """Send a message to another user."""
        if not self.logged_in:
            print("Must be logged in to send messages")
            return False

        message = Message(
            type=MessageType.SEND_MESSAGE,
            payload={"text": text},
            sender=self.username,
            recipient=recipient,
            timestamp=time.time(),
        )
        return self._send_message_no_response(message)

    def receive_messages(self) -> None:
        """Continuously read inbound messages using length framing."""
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

                if message.type == MessageType.SUCCESS:
                    print("message received is:", text)
                    if "Login successful" or "Account created" in text:
                        self.logged_in = True
                    print(f"[SUCCESS] {text}")
                elif message.type == MessageType.ERROR:
                    print(f"[ERROR] {text}")
                elif message.sender == "SERVER":
                    print(f"[SERVER] {text}")
                else:
                    print(f"[{message.sender}] {text}")

            except Exception as e:
                print(f"Error in receive thread: {e}")
                break

        self.running = False
        self.close()

    def close(self) -> None:
        """Close the socket connection."""
        self.running = False
        try:
            self.socket.close()
            print("Connection closed.")
        except Exception as e:
            print(f"Error closing connection: {e}")


def get_password(prompt: str) -> str:
    """Securely get password from user."""
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
    args = parser.parse_args()

    client = ChatClient(username=args.username, protocol_type=args.protocol)

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
                client.login(password)
            else:
                print("Invalid choice")
                sys.exit(1)

            print("\nCommands:")
            print("1. Send message: <recipient>,<message>")
            print("2. Delete account: !delete")
            print("Press Ctrl+C to quit")

            while True:
                message = input()
                if not message:
                    break

                if message.strip().lower() == "!delete":
                    if (
                        input("Are you sure you want to delete your account? (yes/no): ").lower()
                        == "yes"
                    ):
                        client.delete_account()
                        break
                    continue

                if "," not in message:
                    print("Invalid format. Use: <recipient>,<message>")
                    continue

                recipient, text = message.split(",", 1)
                client.send_message(recipient, text)
        else:
            print("Could not connect to server.")
    except KeyboardInterrupt:
        print("\nClient interrupted (Ctrl+C)")
    finally:
        client.close()
