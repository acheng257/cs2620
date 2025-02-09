import streamlit as st
import socket
import json
import time
import os
from typing import Optional, Dict, Any
from protocols.base import Message, MessageType
# from protocols.json_protocol import JsonProtocol
# from protocols.binary_protocol import BinaryProtocol

class ChatClient:
    def __init__(self, host: str="127.0.0.1", port: int=54400, use_json: bool = True):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # self.protocol = JsonProtocol() if use_json else BinaryProtocol()

    def connect(self):
        try:
            self.socket.connect((self.host, self.port))
            # self.socket.send(b"J" if isinstance(self.protocol, JsonProtocol) else b"B")
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            return False
        
    def send_message(self, message: Message) -> Optional[Message]:
        """Send a message to the server and receive the response."""
        try:
            message_bytes = message.encode('utf-8')  # Encode the string to bytes
            self.socket.sendall(message_bytes)  # Send the bytes
            data = self.socket.recv(1024)  # Receive up to 1024 bytes
            response = data.decode('utf-8')  # Decode the response bytes to a string
            print("Response from server is", response)
            return response
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
            message = "123,testing"
            response = client.send_message(message)
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