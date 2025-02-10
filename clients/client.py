import streamlit as st
import socket
import json
import time
import os
from typing import Optional, Dict, Any
from protocols.base import Message, MessageType
from protocols.binary_protocol import BinaryProtocol

class ChatClient:
    def __init__(self, host: str="127.0.0.1", port: int=54400, use_json: bool = True):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # self.protocol = JsonProtocol() if use_json else BinaryProtocol()
        self.protocol = BinaryProtocol()

    def connect(self):
        try:
            self.socket.connect((self.host, self.port))
            self.socket.send(b"B")
            # self.socket.send(b"J" if isinstance(self.protocol, JsonProtocol) else b"B")
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            return False
        
    def send_message(self, message: Message) -> Optional[Message]:
        """Send a message to the server and receive the response."""
        try:
            data = self.protocol.serialize(message)
            length = len(data)
            self.socket.send(length.to_bytes(4, "big"))
            self.socket.send(data)

            # Receive response
            length_bytes = self.socket.recv(4)
            if not length_bytes:
                return None

            message_length = int.from_bytes(length_bytes, "big")
            message_data = self.socket.recv(message_length)

            if not message_data:
                return None

            return self.protocol.deserialize(message_data)
        except Exception as e:
            print(f"Communication error: {e}")
            return None
        
    def close(self):
        """Close the socket connection."""
        try:
            self.socket.close()
            print("Connection closed.")
        except Exception as e:
            print(f"Error closing connection: {e}")
        
if __name__ == '__main__':
    client = ChatClient()
    try:
        if client.connect():
            message_obj = Message(
                type=MessageType.SEND_MESSAGE,
                payload={"text": "123,testing"},
                sender="alice",
                recipient="bob",
                timestamp=time.time()
            )

            response = client.send_message(message_obj)

            if response:
                print(f"Received response: {response}")
            else:
                print("No response received.")
        else:
            print("Failed to connect to server.")
    except KeyboardInterrupt:
        print("Client interrupted (Ctrl+C)")
    finally:
        client.close()