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
        # Initially create a channel; however, if host/port change, we'll recreate it in connect()
        self.channel = grpc.insecure_channel(f"{self.host}:{self.port}")
        self.stub = chat_pb2_grpc.ChatServerStub(self.channel)
        self.logged_in = False
        self.read_thread: Optional[threading.Thread] = None
        self.leader_check_thread: Optional[threading.Thread] = None
        self.running = True
        self.incoming_messages_queue: queue.Queue = queue.Queue()

    def connect(self, timeout: int = 5) -> bool:
        """
        Checks the connection by (re)creating the gRPC channel based on the current
        host and port, and then performing a dummy RPC call (health-check) to verify the server
        is actually responding.

        Returns True if the health-check call succeeds, False otherwise.
        """
        # Recreate the channel and stub using the current host and port values.
        self.channel = grpc.insecure_channel(f"{self.host}:{self.port}")
        self.stub = chat_pb2_grpc.ChatServerStub(self.channel)

        try:
            grpc.channel_ready_future(self.channel).result(timeout=timeout)
        except grpc.FutureTimeoutError:
            error_message = (
                f"Failed to connect to server at {self.host}:{self.port} within {timeout} seconds."
            )
            print(error_message)
            return False

        dummy_payload = {"pattern": "", "page": 1}
        # Time serialization for dummy_payload.
        start_ser = time.perf_counter()
        parsed_dummy = ParseDict(dummy_payload, Struct())
        end_ser = time.perf_counter()
        print(f"[connect] Serialization took {end_ser - start_ser:.6f} seconds")

        dummy_request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LIST_ACCOUNTS,
            payload=parsed_dummy,
            sender="",  # sender is irrelevant for a health-check
            recipient="SERVER",
            timestamp=time.time(),
        )
        try:
            _ = self.stub.ListAccounts(dummy_request)
            print(f"Connected to server at {self.host}:{self.port}")
            return True
        except grpc.RpcError as e:
            error_message = f"Health-check RPC failed: {e.details()}"
            print(error_message)
            return False

    def create_account(self, password: str) -> None:
        payload = {"username": self.username, "password": password}
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(payload, Struct())
        end_ser = time.perf_counter()
        print(f"[create_account] Serialization took {end_ser - start_ser:.6f} seconds")

        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.CREATE_ACCOUNT,
            payload=parsed_payload,
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.CreateAccount(message)
        start_deser = time.perf_counter()
        # In this method we don't explicitly call MessageToDict on the response,
        # so only the stub's work is measured externally.
        _ = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(f"[create_account] Deserialization took {end_deser - start_deser:.6f} seconds")
        if response.type == chat_pb2.MessageType.SUCCESS:
            print("Account created successfully.")
        else:
            print("Account creation failed.")

    def create_account_sync(self, password: str) -> bool:
        """
        Synchronous account creation wrapper.
        """
        payload = {"username": self.username, "password": password}
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(payload, Struct())
        end_ser = time.perf_counter()
        print(f"[create_account_sync] Serialization took {end_ser - start_ser:.6f} seconds")

        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.CREATE_ACCOUNT,
            payload=parsed_payload,
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.CreateAccount(message)
        start_deser = time.perf_counter()
        _ = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(f"[create_account_sync] Deserialization took {end_deser - start_deser:.6f} seconds")
        return response.type == chat_pb2.MessageType.SUCCESS

    def login(self, password: str) -> bool:
        payload = {"username": self.username, "password": password}
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(payload, Struct())
        end_ser = time.perf_counter()
        print(f"[login] Serialization took {end_ser - start_ser:.6f} seconds")

        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LOGIN,
            payload=parsed_payload,
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.Login(message)
        start_deser = time.perf_counter()
        deser = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(f"[login] Deserialization took {end_deser - start_deser:.6f} seconds")

        if response.type == chat_pb2.MessageType.SUCCESS:
            self.logged_in = True
            details = deser.get("text", "")
            print(f"Login successful. {details}")
        else:
            self.logged_in = False
            error_text = deser.get("text", "Login failed.")
            print(f"Login failed: {error_text}")
        return self.logged_in

    def login_sync(self, password: str) -> Tuple[bool, Optional[str]]:
        payload = {"username": self.username, "password": password}
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(payload, Struct())
        end_ser = time.perf_counter()
        print(f"[login_sync] Serialization took {end_ser - start_ser:.6f} seconds")

        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LOGIN,
            payload=parsed_payload,
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.Login(message)
        start_deser = time.perf_counter()
        deser = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(f"[login_sync] Deserialization took {end_deser - start_deser:.6f} seconds")

        if response.type == chat_pb2.MessageType.SUCCESS:
            self.logged_in = True
            return True, None
        else:
            self.logged_in = False
            error_text = deser.get("text", "Login failed.")
            return False, error_text

    def send_message(self, recipient: str, text: str) -> bool:
        try:
            payload = {"text": text}
            start_ser = time.perf_counter()
            parsed_payload = ParseDict(payload, Struct())
            end_ser = time.perf_counter()
            print(f"[send_message] Serialization took {end_ser - start_ser:.6f} seconds")

            message = chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SEND_MESSAGE,
                payload=parsed_payload,
                sender=self.username,
                recipient=recipient,
                timestamp=time.time(),
            )
            response = self.stub.SendMessage(message)
            start_deser = time.perf_counter()
            _ = MessageToDict(response.payload)
            end_deser = time.perf_counter()
            print(f"[send_message] Deserialization took {end_deser - start_deser:.6f} seconds")

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
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(payload, Struct())
        end_ser = time.perf_counter()
        print(f"[send_message_sync] Serialization took {end_ser - start_ser:.6f} seconds")

        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SEND_MESSAGE,
            payload=parsed_payload,
            sender=self.username,
            recipient=recipient,
            timestamp=time.time(),
        )
        response = self.stub.SendMessage(message)
        start_deser = time.perf_counter()
        _ = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(f"[send_message_sync] Deserialization took {end_deser - start_deser:.6f} seconds")
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
                # Optionally, you could measure deserialization for each streamed message.
                start_deser = time.perf_counter()
                _ = MessageToDict(msg.payload)
                end_deser = time.perf_counter()
                print(f"[read_messages] Deserialization took {end_deser - start_deser:.6f} seconds")
                self.incoming_messages_queue.put(msg)
        except grpc.RpcError as e:
            print("Message stream closed:", e)

    def start_read_thread(self) -> None:
        if self.read_thread is None:
            self.read_thread = threading.Thread(target=self.read_messages, daemon=True)
            self.read_thread.start()
            self.start_leader_check_thread()  # Start leader check when starting read thread

    def list_accounts(self, pattern: str = "", page: int = 1) -> None:
        payload = {"pattern": pattern, "page": page}
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(payload, Struct())
        end_ser = time.perf_counter()
        print(f"[list_accounts] Serialization took {end_ser - start_ser:.6f} seconds")

        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LIST_ACCOUNTS,
            payload=parsed_payload,
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.ListAccounts(message)
        start_deser = time.perf_counter()
        result = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(f"[list_accounts] Deserialization took {end_deser - start_deser:.6f} seconds")
        print("Accounts list:", result)

    def list_accounts_sync(self, pattern: str = "", page: int = 1) -> chat_pb2.ChatMessage:
        payload = {"pattern": pattern, "page": page}
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(payload, Struct())
        end_ser = time.perf_counter()
        print(f"[list_accounts_sync] Serialization took {end_ser - start_ser:.6f} seconds")

        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LIST_ACCOUNTS,
            payload=parsed_payload,
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.ListAccounts(message)
        start_deser = time.perf_counter()
        _ = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(f"[list_accounts_sync] Deserialization took {end_deser - start_deser:.6f} seconds")
        return response

    def delete_messages(self, message_ids: list) -> None:
        payload = {"message_ids": message_ids}
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(payload, Struct())
        end_ser = time.perf_counter()
        print(f"[delete_messages] Serialization took {end_ser - start_ser:.6f} seconds")

        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.DELETE_MESSAGES,
            payload=parsed_payload,
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.DeleteMessages(message)
        start_deser = time.perf_counter()
        _ = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(f"[delete_messages] Deserialization took {end_deser - start_deser:.6f} seconds")
        if response.type == chat_pb2.MessageType.SUCCESS:
            print("Messages deleted successfully.")
        else:
            print("Failed to delete messages.")

    def delete_messages_sync(self, message_ids: List[int]) -> chat_pb2.ChatMessage:
        payload = {"message_ids": message_ids}
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(payload, Struct())
        end_ser = time.perf_counter()
        print(f"[delete_messages_sync] Serialization took {end_ser - start_ser:.6f} seconds")

        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.DELETE_MESSAGES,
            payload=parsed_payload,
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.DeleteMessages(message)
        start_deser = time.perf_counter()
        _ = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(f"[delete_messages_sync] Deserialization took {end_deser - start_deser:.6f} seconds")
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
        start_deser = time.perf_counter()
        _ = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(f"[delete_account] Deserialization took {end_deser - start_deser:.6f} seconds")
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
        start_deser = time.perf_counter()
        _ = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(f"[delete_account_sync] Deserialization took {end_deser - start_deser:.6f} seconds")
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
            start_deser = time.perf_counter()
            result = MessageToDict(response.payload)
            end_deser = time.perf_counter()
            print(
                f"[list_chat_partners] Deserialization took {end_deser - start_deser:.6f} seconds"
            )
            if response is None:
                print("No response received from ListChatPartners RPC.")
                return None
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
        start_deser = time.perf_counter()
        _ = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(
            f"[list_chat_partners_sync] Deserialization took {end_deser - start_deser:.6f} seconds"
        )
        return response

    def read_conversation(
        self, partner: str, offset: int = 0, limit: int = 50
    ) -> List[Dict[str, Any]]:
        payload = {"partner": partner, "offset": offset, "limit": limit}
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(payload, Struct())
        end_ser = time.perf_counter()
        print(f"[read_conversation] Serialization took {end_ser - start_ser:.6f} seconds")

        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.READ_MESSAGES,  # or use READ_CONVERSATION if defined
            payload=parsed_payload,
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        try:
            response = self.stub.ReadConversation(message)
            start_deser = time.perf_counter()
            deser = MessageToDict(response.payload)
            end_deser = time.perf_counter()
            print(f"[read_conversation] Deserialization took {end_deser - start_deser:.6f} seconds")
            if response and response.type == chat_pb2.MessageType.SUCCESS:
                return deser.get("messages", [])
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
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(payload, Struct())
        end_ser = time.perf_counter()
        print(f"[read_conversation_sync] Serialization took {end_ser - start_ser:.6f} seconds")

        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.READ_MESSAGES,
            payload=parsed_payload,
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.ReadConversation(message)
        start_deser = time.perf_counter()
        _ = MessageToDict(response.payload)
        end_deser = time.perf_counter()
        print(
            f"[read_conversation_sync] Deserialization took {end_deser - start_deser:.6f} seconds"
        )
        return response

    def close(self) -> None:
        self.running = False
        if self.channel:
            self.channel.close()

    def _check_leader(self) -> None:
        """Periodically check if we're still connected to the leader"""
        while self.running:
            try:
                leader = self.get_leader()
                if leader:
                    leader_host, leader_port = leader
                    if leader_host != self.host or leader_port != self.port:
                        print(f"Leader changed to {leader_host}:{leader_port}, reconnecting...")
                        self.host = leader_host
                        self.port = leader_port
                        self.connect()
            except Exception as e:
                print(f"Error checking leader: {e}")
            time.sleep(5)  # Check every 5 seconds

    def start_leader_check_thread(self) -> None:
        """Start the leader check thread"""
        if self.leader_check_thread is None:
            self.leader_check_thread = threading.Thread(target=self._check_leader, daemon=True)
            self.leader_check_thread.start()


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
    if client.connect():
        print("Client connected successfully.")
    else:
        print("Client failed to connect. Please check the host and port.")
        exit(1)
    client.start_read_thread()
    print("Client connected. Implement interactive commands as needed.")
