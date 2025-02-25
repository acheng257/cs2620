import argparse
import queue
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

from src.protocols.grpc import chat_pb2, chat_pb2_grpc


class ChatClient:
    """
    A gRPC-based client for the chat system with synchronous wrapper methods.
    """

    def __init__(self, username: str, host: str = "127.0.0.1", port: int = 50051) -> None:
        self.username = username
        self.host = host
        self.port = port
        self.channel = grpc.insecure_channel(f"{host}:{port}")
        self.stub = chat_pb2_grpc.ChatServerStub(self.channel)
        self.logged_in = False
        self.read_thread: Optional[threading.Thread] = None
        self.running = True
        self.incoming_messages_queue: queue.Queue = queue.Queue()  # NEW: for realtime messages

    def connect(self) -> bool:
        """
        For gRPC, connection is established on initialization.
        """
        return True

    def create_account(self, password: str) -> None:
        payload = {"username": self.username, "password": password}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.CREATE_ACCOUNT,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.CreateAccount(message)
        if response.type == chat_pb2.MessageType.SUCCESS:
            print("Account created successfully.")
        else:
            print("Account creation failed.")

    def create_account_sync(self, password: str) -> bool:
        """
        Synchronous account creation wrapper.
        """
        payload = {"username": self.username, "password": password}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.CREATE_ACCOUNT,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.CreateAccount(message)
        if response.type == chat_pb2.MessageType.SUCCESS:
            return True
        else:
            return False

    def login(self, password: str) -> bool:
        payload = {"username": self.username, "password": password}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LOGIN,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.Login(message)
        if response.type == chat_pb2.MessageType.SUCCESS:
            self.logged_in = True
            details = MessageToDict(response.payload).get("text", "")
            print(f"Login successful. {details}")
        else:
            error_text = MessageToDict(response.payload).get("text", "Login failed.")
            print(f"Login failed: {error_text}")
        return self.logged_in

    def login_sync(self, password: str) -> Tuple[bool, Optional[str]]:
        """
        Synchronous login wrapper that returns (success, error_message).
        """
        payload = {"username": self.username, "password": password}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LOGIN,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.Login(message)
        if response.type == chat_pb2.MessageType.SUCCESS:
            self.logged_in = True
            return True, None
        else:
            error_text = MessageToDict(response.payload).get("text", "Login failed.")
            return False, error_text

    def send_message(self, recipient: str, text: str) -> bool:
        try:
            payload = {"text": text}
            message = chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SEND_MESSAGE,
                payload=ParseDict(payload, Struct()),
                sender=self.username,
                recipient=recipient,
                timestamp=time.time(),
            )
            response = self.stub.SendMessage(message)
            if response.type == chat_pb2.MessageType.SUCCESS:
                print("Message sent successfully.")
                return True
            elif response.type == chat_pb2.MessageType.ERROR:
                error_message = MessageToDict(response.payload).get("text", "Unknown error.")
                print(f"Error sending message: {error_message}")
                return False
            else:
                print("Unexpected response from server.")
                return False
        except grpc.RpcError as e:
            print(f"RPC error while sending message: {e.details()}")
            return False

    def send_message_sync(self, recipient: str, text: str) -> chat_pb2.ChatMessage:
        payload = {"text": text}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SEND_MESSAGE,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient=recipient,
            timestamp=time.time(),
        )
        response = self.stub.SendMessage(message)
        return response

    def read_messages(self) -> None:
        """
        Listen for incoming messages using the streaming ReadMessages RPC.
        Push received messages to incoming_messages_queue.
        """
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.READ_MESSAGES,
            payload=Struct(),  # empty payload
            sender=self.username,
            recipient=self.username,
            timestamp=time.time(),
        )
        try:
            for msg in self.stub.ReadMessages(message):
                self.incoming_messages_queue.put(msg)
        except grpc.RpcError as e:
            print("Message stream closed:", e)

    def start_read_thread(self) -> None:
        if self.read_thread is None:
            self.read_thread = threading.Thread(target=self.read_messages, daemon=True)
            self.read_thread.start()

    def list_accounts(self, pattern: str = "", page: int = 1) -> None:
        payload = {"pattern": pattern, "page": page}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LIST_ACCOUNTS,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.ListAccounts(message)
        result = MessageToDict(response.payload)
        print("Accounts list:", result)

    def list_accounts_sync(self, pattern: str = "", page: int = 1) -> chat_pb2.ChatMessage:
        payload = {"pattern": pattern, "page": page}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LIST_ACCOUNTS,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.ListAccounts(message)
        return response

    def delete_messages(self, message_ids: list) -> None:
        payload = {"message_ids": message_ids}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.DELETE_MESSAGES,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.DeleteMessages(message)
        if response.type == chat_pb2.MessageType.SUCCESS:
            print("Messages deleted successfully.")
        else:
            print("Failed to delete messages.")

    def delete_messages_sync(self, message_ids: List[int]) -> chat_pb2.ChatMessage:
        payload = {"message_ids": message_ids}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.DELETE_MESSAGES,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.DeleteMessages(message)
        return response

    def delete_account(self) -> None:
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.DELETE_ACCOUNT,
            payload=Struct(),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.DeleteAccount(message)
        if response.type == chat_pb2.MessageType.SUCCESS:
            print("Account deleted successfully.")
        else:
            print("Failed to delete account.")

    def delete_account_sync(self) -> chat_pb2.ChatMessage:
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.DELETE_ACCOUNT,
            payload=Struct(),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.DeleteAccount(message)
        return response

    def list_chat_partners(self):
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LIST_CHAT_PARTNERS,
            payload=Struct(),  # no additional data needed
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        try:
            response = self.stub.ListChatPartners(message)
            if response is None:
                print("No response received from ListChatPartners RPC.")
                return None
            result = MessageToDict(response.payload)
            print("Chat partners:", result)
            return result
        except grpc.RpcError as e:
            print(f"RPC error in list_chat_partners: {e.details()}")
            return None

    def list_chat_partners_sync(self) -> chat_pb2.ChatMessage:
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LIST_CHAT_PARTNERS,
            payload=Struct(),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.ListChatPartners(message)
        return response

    def read_conversation(
        self, partner: str, offset: int = 0, limit: int = 50
    ) -> List[Dict[str, Any]]:
        payload = {"partner": partner, "offset": offset, "limit": limit}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.READ_MESSAGES,  # or use READ_CONVERSATION if defined
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        try:
            response = self.stub.ReadConversation(message)
            if response and response.type == chat_pb2.MessageType.SUCCESS:
                result = MessageToDict(response.payload)
                return result.get("messages", [])
            else:
                print("Failed to read conversation.")
                return []
        except grpc.RpcError as e:
            print(f"RPC error in read_conversation: {e.details()}")
            return []

    def read_conversation_sync(
        self, partner: str, offset: int = 0, limit: int = 50
    ) -> chat_pb2.ChatMessage:
        payload = {"partner": partner, "offset": offset, "limit": limit}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.READ_MESSAGES,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.ReadConversation(message)
        return response

    def close(self) -> None:
        self.running = False
        if self.channel:
            self.channel.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="gRPC Chat Client")
    parser.add_argument("username", help="Your chat username")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Server host to connect to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=50051,
        help="Server port to connect to (default: 50051)",
    )
    args = parser.parse_args()

    client = ChatClient(username=args.username, host=args.host, port=args.port)
    # Example usage:
    client.start_read_thread()
    print("Client connected. Implement interactive commands as needed.")
