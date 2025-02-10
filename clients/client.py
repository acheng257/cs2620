import streamlit as st
import socket
import json
import time
import os
import threading
from typing import Optional, Dict, Any
from protocols.base import Message, MessageType


class ChatClient:
    def __init__(self, username: str, host: str = "127.0.0.1", port: int = 54400):
        self.host = host
        self.port = port
        self.username = username
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = False
        self.receive_thread = None

    def connect(self):
        try:
            self.socket.connect((self.host, self.port))
            # Send initial message with username
            self.send_message(f"{self.username},connected")
            self.running = True
            # Start receive thread
            self.receive_thread = threading.Thread(target=self.receive_messages)
            self.receive_thread.daemon = True
            self.receive_thread.start()
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            return False

    def send_message(self, message: str) -> bool:
        """Send a message to the server."""
        try:
            message_bytes = message.encode("utf-8")
            self.socket.sendall(message_bytes)
            return True
        except Exception as e:
            print(f"Error sending message: {e}")
            return False

    def receive_messages(self):
        """Continuously receive messages from the server."""
        while self.running:
            try:
                data = self.socket.recv(1024)
                if not data:
                    break
                message = data.decode("utf-8")
                content, sender_username = message.split(",", 1)

                if sender_username == "SERVER":
                    print(f"Server message: {content}")
                else:
                    print(f"User [{sender_username}] says: {content}")
            except Exception as e:
                print(f"Error receiving message: {e}")
                break
        self.running = False

    def close(self):
        """Close the socket connection."""
        self.running = False
        try:
            self.socket.close()
            print("Connection closed.")
        except Exception as e:
            print(f"Error closing connection: {e}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python client.py <username>")
        sys.exit(1)

    username = sys.argv[1]
    client = ChatClient(username)

    try:
        if client.connect():
            print(f"Connected to server as {username}")
            print("Type messages in format: <recipient_username>,<message>")
            print("Example: alice,Hello World!")
            print("Press Ctrl+C to quit")

            while True:
                message = input()
                if not client.running:
                    break
                if "," not in message:
                    print("Invalid format. Use: <recipient_username>,<message>")
                    continue
                client.send_message(message)
        else:
            print("Failed to connect to server.")
    except KeyboardInterrupt:
        print("\nClient interrupted (Ctrl+C)")
    finally:
        client.close()
