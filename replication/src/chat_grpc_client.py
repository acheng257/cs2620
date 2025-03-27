"""
A gRPC-based client for the chat system with leader-follower replication support.

This module provides the ChatClient class which handles:
1. Connection to the chat server cluster
2. Leader discovery and automatic reconnection
3. Message sending and receiving
4. Account management
5. Chat history and conversation management

The client maintains a connection to the leader server and automatically handles leader changes
by discovering and reconnecting to the new leader when needed. It uses a cluster configuration
to maintain a list of all possible servers and implements retry logic for robustness.
"""

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
    A gRPC-based client for the chat system with leader-follower replication support.

    This class provides a high-level interface to interact with the chat server cluster,
    handling leader discovery, automatic reconnection, and all chat operations. It maintains
    background threads for reading messages and checking leader status.

    Attributes:
        username (str): The user's username for authentication
        host (str): Current server host address
        port (int): Current server port number
        cluster_nodes (List[Tuple[str, int]]): List of all known server addresses
        channel (grpc.Channel): gRPC channel for server communication
        stub (chat_pb2_grpc.ChatServerStub): gRPC stub for making RPC calls
        logged_in (bool): Whether the user is currently logged in
        read_thread (Optional[threading.Thread]): Thread for reading incoming messages
        leader_check_thread (Optional[threading.Thread]): Thread for monitoring leader status
        running (bool): Flag to control background threads
        incoming_messages_queue (queue.Queue): Queue for incoming messages

    Args:
        username (str): The user's username
        host (str, optional): Initial server host. Defaults to "127.0.0.1"
        port (int, optional): Initial server port. Defaults to 50051
        cluster_nodes (Optional[List[Tuple[str, int]]], optional): List of server addresses.
            If None, uses [(host, port)]. Defaults to None.
    """

    def __init__(
        self,
        username: str,
        host: str = "127.0.0.1",
        port: int = 50051,
        cluster_nodes: Optional[List[Tuple[str, int]]] = None,
    ) -> None:
        self.username = username
        self.host = host
        self.port = port
        self.cluster_nodes = cluster_nodes or [(host, port)]
        self.channel = grpc.insecure_channel(f"{self.host}:{self.port}")
        self.stub = chat_pb2_grpc.ChatServerStub(self.channel)
        self.logged_in = False
        self.read_thread: Optional[threading.Thread] = None
        self.leader_check_thread: Optional[threading.Thread] = None
        self.running = True
        self.incoming_messages_queue: queue.Queue = queue.Queue()

    def connect(self, timeout: int = 5) -> bool:
        """
        Establish a connection to the server and verify it's responding.

        Creates a new gRPC channel using the current host and port, then performs
        a health-check RPC call to verify the connection. The health-check uses
        a lightweight ListAccounts call with empty parameters.

        Args:
            timeout (int, optional): Connection timeout in seconds. Defaults to 5.

        Returns:
            bool: True if connection and health-check succeed, False otherwise.
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
        """
        Create a new user account.

        This is the asynchronous version of create_account_sync. It prints success/failure
        messages instead of returning a status.

        Args:
            password (str): The password for the new account
        """
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
        Create a new user account (synchronous version).

        Args:
            password (str): The password for the new account

        Returns:
            bool: True if account creation succeeded, False otherwise
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
        """
        Log in to an existing account.

        This is the asynchronous version of login_sync. It updates the logged_in
        state and prints success/failure messages.

        Args:
            password (str): The account password

        Returns:
            bool: True if login succeeded, False otherwise
        """
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
        """
        Log in to an existing account (synchronous version).

        Args:
            password (str): The account password

        Returns:
            Tuple[bool, Optional[str]]: A tuple containing:
                - bool: True if login succeeded, False otherwise
                - Optional[str]: Error message if login failed, None if successful
        """
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
        """
        Send a message to another user.

        This method implements retry logic for leader changes, attempting to send
        the message multiple times if the leader changes during the operation.

        Args:
            recipient (str): Username of the message recipient
            text (str): Content of the message

        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        max_retries = 20
        retry_delay = 1.0  # seconds

        for attempt in range(max_retries):
            try:
                payload = {"text": text}
                parsed_payload = ParseDict(payload, Struct())

                message = chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.SEND_MESSAGE,
                    payload=parsed_payload,
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

                    # If error indicates leader issues, wait for leader election
                    if "leader" in error_message.lower():
                        if attempt < max_retries - 1:  # Don't sleep on last attempt
                            print(
                                f"Waiting for leader election (attempt {attempt + 1}/{max_retries})..."
                            )
                            time.sleep(retry_delay)
                            continue
                    return False
                else:
                    print("Unexpected response from server.")
                    return False

            except grpc.RpcError as e:
                print(f"RPC error while sending message: {e.details()}")
                if attempt < max_retries - 1:  # Don't sleep on last attempt
                    print(
                        f"Retrying in {retry_delay} seconds (attempt {attempt + 1}/{max_retries})..."
                    )
                    time.sleep(retry_delay)
                    continue
                return False

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
        Listen for incoming messages in a background thread.

        This method establishes a streaming RPC connection to receive messages
        in real-time. Received messages are placed in the incoming_messages_queue.
        The method runs continuously while self.running is True.
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
        """
        Start background threads for reading messages and checking leader status.

        This method starts two daemon threads:
        1. A thread for reading incoming messages (read_messages)
        2. A thread for monitoring leader status (leader_check_thread)

        The threads will automatically terminate when the program exits.
        """
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
        """
        Clean up resources and stop background threads.

        This method:
        1. Sets running to False to stop background threads
        2. Closes the gRPC channel
        Should be called when the client is no longer needed.
        """
        self.running = False
        if self.channel:
            self.channel.close()

    def _check_leader(self) -> None:
        """
        Periodically check if we're still connected to the leader server.

        This method runs in a background thread and:
        1. Checks if the current connection is to the leader
        2. If not, attempts to get leader information from current server
        3. If that fails, tries all known cluster nodes to find the leader
        4. When a new leader is found, updates the connection
        5. Restarts the read thread with the new connection

        The check runs every 200ms while self.running is True.
        """
        while self.running:
            try:
                # Try current connection first
                try:
                    leader = self.get_leader()
                    if leader:
                        leader_host, leader_port = leader
                        if leader_host != self.host or leader_port != self.port:
                            print(f"Leader changed to {leader_host}:{leader_port}, reconnecting...")
                            self.host = leader_host
                            self.port = leader_port
                            if self.connect():
                                print("Successfully reconnected to new leader")
                                # Restart read thread with new connection
                                if self.read_thread:
                                    self.read_thread = None
                                    self.start_read_thread()
                            else:
                                print("Failed to connect to new leader, will try other servers...")
                                raise Exception("Failed to connect to leader")
                except Exception:
                    # Current connection failed, try all known cluster nodes
                    found_leader = False
                    for node_host, node_port in self.cluster_nodes:
                        if (node_host, node_port) != (
                            self.host,
                            self.port,
                        ):  # Don't try current node
                            try:
                                temp_client = ChatClient(
                                    username="",
                                    host=node_host,
                                    port=node_port,
                                    cluster_nodes=self.cluster_nodes,
                                )
                                if temp_client.connect(timeout=1):  # Shorter timeout for discovery
                                    leader = temp_client.get_leader()
                                    temp_client.close()
                                    if leader:
                                        leader_host, leader_port = leader
                                        print(
                                            f"Found leader through {node_host}:{node_port}: {leader_host}:{leader_port}"
                                        )
                                        self.host = leader_host
                                        self.port = leader_port
                                        if self.connect():
                                            print("Successfully reconnected to leader")
                                            if self.read_thread:
                                                self.read_thread = None
                                                self.start_read_thread()
                                            found_leader = True
                                            break
                            except Exception as e:
                                print(f"Failed to check node {node_host}:{node_port}: {e}")
                                continue

                    if not found_leader:
                        print("Could not find leader through any known nodes, will retry...")

            except Exception as e:
                print(f"Error in leader check: {e}")

            time.sleep(0.2)  # Check every 200ms

    def start_leader_check_thread(self) -> None:
        """
        Start the background thread that monitors leader status.

        This method starts a daemon thread that runs the _check_leader method.
        The thread will automatically terminate when the program exits.
        The thread is only started if it's not already running.
        """
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
