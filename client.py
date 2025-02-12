# client.py
import argparse
import socket
import time
import threading
import sys
import getpass
import queue 
from protocols.base import Message, MessageType
from protocols.json_protocol import JsonProtocol
from protocols.binary_protocol import BinaryProtocol

class ChatClient:
    def __init__(self, username, protocol_type, host="127.0.0.1", port=54400):
        self.host = host
        self.port = port
        self.username = username
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = False
        self.receive_thread = None
        self.logged_in = False

        if protocol_type.upper().startswith("J"):
            self.protocol_byte = b"J"
            self.protocol = JsonProtocol()
        else:
            self.protocol_byte = b"B"
            self.protocol = BinaryProtocol()

        # synchronous response waiting
        self.response_lock = threading.Lock()
        self.last_response = None

        # queue to hold real-time pushed messages from the server
        self.incoming_messages_queue = queue.Queue()

    def connect(self) -> bool:
        try:
            self.socket.connect((self.host, self.port))
            self.socket.sendall(self.protocol_byte)
            self.running = True

            # Start thread that continuously reads incoming messages
            self.receive_thread = threading.Thread(
                target=self.receive_messages, daemon=True
            )
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

    def _send_message_and_wait(self, message: Message, timeout: float = 10.0):
        """Send a message and wait for a response within a timeout."""
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
    
    def read_conversation_sync(self, other_user: str, offset=0, limit=20):
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


    def list_accounts_sync(self, pattern="", page=1):
        """Send LIST_ACCOUNTS request and wait for the server's response."""
        msg = Message(
            type=MessageType.LIST_ACCOUNTS,
            payload={"pattern": pattern, "page": page},
            sender=self.username,
            recipient="SERVER",
        )
        response = self._send_message_and_wait(msg)
        return response
    
    def list_chat_partners_sync(self):
        """
        Ask the server for a list of all chat partners for self.username.
        Returns a Message (type=SUCCESS with payload["chat_partners"], or ERROR).
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
        """Create a new account (fire-and-forget)."""
        msg = Message(
            type=MessageType.CREATE_ACCOUNT,
            payload={"username": self.username, "password": password},
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        return self._send_message_no_response(msg)

    def login(self, password: str) -> bool:
        """Log in to an existing account (fire-and-forget)."""
        msg = Message(
            type=MessageType.LOGIN,
            payload={"username": self.username, "password": password},
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        return self._send_message_no_response(msg)

    def delete_account(self) -> bool:
        """Delete the current account (fire-and-forget)."""
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
        return self._send_message_no_response(msg)

    def send_message(self, recipient: str, text: str) -> bool:
        """Send a message to another user."""
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

    def receive_messages(self) -> None:
        """Continuously read inbound messages from the server (push + response)."""
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
                    self.incoming_messages_queue.put(message)

                if message.type == MessageType.SUCCESS:
                    if ("Login successful" in text) or ("Account created" in text):
                        self.logged_in = True

                if message.type == MessageType.SUCCESS:
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

    def close(self):
        """Close the socket connection."""
        self.running = False
        try:
            self.socket.close()
            print("Connection closed.")
        except Exception as e:
            print(f"Error closing connection: {e}")

def list_accounts(client: ChatClient, pattern: str = "", page: int = 1):
    msg = Message(
        type=MessageType.LIST_ACCOUNTS,
        payload={"pattern": pattern, "page": page},
        sender=client.username,
        recipient="SERVER",
        timestamp=time.time(),
    )
    client._send_message_no_response(msg)

def read_messages(client: ChatClient, offset: int = 0, limit: int = 10):
    msg = Message(
        type=MessageType.READ_MESSAGES,
        payload={"offset": offset, "limit": limit},
        sender=client.username,
        recipient="SERVER",
        timestamp=time.time(),
    )
    client._send_message_no_response(msg)

def delete_messages(client: ChatClient, message_ids: list[int]):
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
                msg_input = input()
                if not msg_input:
                    break

                if msg_input.strip().lower() == "!delete":
                    confirm = input("Are you sure you want to delete your account? (yes/no): ")
                    if confirm.lower() == "yes":
                        client.delete_account()
                        break
                    continue

                if "," not in msg_input:
                    print("Invalid format. Use: <recipient>,<message>")
                    continue

                recipient, text = msg_input.split(",", 1)
                client.send_message(recipient, text)
        else:
            print("Could not connect to server.")
    except KeyboardInterrupt:
        print("\nClient interrupted (Ctrl+C)")
    finally:
        client.close()
