import socket
import time
import threading
import sys
from typing import Optional
from protocols.base import Message, MessageType
from protocols.json_protocol import JsonProtocol
from protocols.binary_protocol import BinaryProtocol

class ChatClient:
    def __init__(self, username: str, host: str = "127.0.0.1", port: int = 54400, use_json: bool = False):
        self.host = host
        self.port = port
        self.username = username
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = False
        self.receive_thread: Optional[threading.Thread] = None
        self.protocol = JsonProtocol() if use_json else BinaryProtocol()

    def connect(self) -> bool:
        try:
            self.socket.connect((self.host, self.port))
            self.socket.sendall(b"J" if isinstance(self.protocol, JsonProtocol) else b"B")

            init_msg = Message(
                type=MessageType.LOGIN,
                payload={"text": "initial connection"},
                sender=self.username,
                recipient="server",
                timestamp=time.time(),
            )
            self._send_message_no_response(init_msg)

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

            self.socket.sendall(length.to_bytes(4, "big")) # length of message
            self.socket.sendall(data) # actual message
            return True
        except Exception as e:
            print(f"Communication error: {e}")
            return False

    def send_message(self, recipient: str, text: str) -> bool:
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

                message_content = self.protocol.deserialize(message_data)

                if message_content.sender == "SERVER":
                    print(f"[SERVER] {message_content.payload}")
                else:
                    text = message_content.payload.get("text", "")
                    print(f"[{message_content.sender}] {text}")

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

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python client.py <username>")
        sys.exit(1)

    username = sys.argv[1]
    client = ChatClient(username)

    try:
        if client.connect():
            print(f"Connected to server as {username}")
            print("Type messages as <recipient>,<your text>")
            print("Example: alice,Hello World!")
            print("Press Ctrl+C to quit")

            while True:
                message = input()
                if not message:
                    break

                if "," not in message:
                    print("Invalid format. Use: <recipient_username>,<message>")
                    continue

                recipient, text = message.split(",", 1)
                client.send_message(recipient, text)
        else:
            print("Could not connect to server.")
    except KeyboardInterrupt:
        print("\nClient interrupted (Ctrl+C)")
    finally:
        client.close()