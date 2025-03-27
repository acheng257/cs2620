"""
A gRPC server implementation for the replicated chat system.

This module provides the ChatServer class which implements a leader-follower
replication protocol for a distributed chat system. The server can operate in
three roles:
1. Leader: Handles all client requests and replicates changes to followers
2. Follower: Forwards client requests to the leader and maintains a replica
3. Candidate: Temporarily assumed during leader election

The server provides the following features:
- Account management (creation, login, deletion)
- Message handling (sending, receiving, delivery status)
- Chat history and conversation management
- Leader election and failover
- State replication between servers

The replication protocol ensures:
- Strong consistency for all operations
- Automatic leader election on failure
- Majority acknowledgment for changes
- Automatic client redirection to the leader
"""

import argparse
import queue
import threading
import time
from concurrent import futures
from typing import Dict, List, Optional, Set

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

import src.protocols.grpc.chat_pb2 as chat_pb2
import src.protocols.grpc.chat_pb2_grpc as chat_pb2_grpc
from src.database.db_manager import DatabaseManager
from src.replication.replication_manager import ReplicationManager, ServerRole, heartbeat_logger

import logging


# Create a custom formatter for better readability
class CustomFormatter(logging.Formatter):
    """Custom formatter that includes server info and colors for different levels"""

    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format_str = "%(asctime)s - %(levelname)s - [%(server_info)s] %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: grey + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


# Create server logger
server_logger = logging.getLogger("server")
server_logger.setLevel(logging.INFO)

# Add handler with the custom formatter
handler = logging.StreamHandler()
handler.setFormatter(CustomFormatter())
server_logger.addHandler(handler)


class ChatServer(chat_pb2_grpc.ChatServerServicer):
    """
    gRPC server implementation for the replicated chat service.

    This class implements the chat service defined in chat.proto, handling all
    client requests and managing replication between servers. It integrates with
    ReplicationManager for leader-follower coordination and DatabaseManager for
    persistent storage.

    The server maintains:
    - Active user connections and their message queues
    - Message delivery and read status
    - Account state and authentication
    - Leader-follower replication state

    Attributes:
        host (str): Server's bind address
        port (int): Server's bind port
        db (DatabaseManager): Database connection manager
        active_users (Dict[str, Set[chat_pb2_grpc.ChatServer_SubscribeStub]]):
            Map of usernames to their active connections
        lock (threading.Lock): Lock for thread-safe operations
        replication_manager (ReplicationManager): Manages leader-follower protocol

    Args:
        host (str, optional): Address to bind the server on. Defaults to "0.0.0.0"
        port (int, optional): Port to bind the server on. Defaults to 50051
        db_path (str, optional): Path to the SQLite database file.
            Defaults to None (uses port-specific path)
        replica_addresses (List[str], optional): List of other servers in the cluster.
            Defaults to None
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 50051,
        db_path: str = None,
        replica_addresses: List[str] = None,
        cluster_nodes=None,
    ) -> None:
        self.host = host
        self.port = port
        # Use port-specific database path if not provided
        if db_path is None:
            db_path = f"chat_{port}.db"
        self.db: DatabaseManager = DatabaseManager(db_path)
        self.active_users: Dict[str, Set[chat_pb2_grpc.ChatServer_SubscribeStub]] = {}
        self.lock: threading.Lock = threading.Lock()

        # Add server info to logging context
        self.logger = logging.LoggerAdapter(server_logger, {"server_info": f"{host}:{port}"})

        self.replication_manager = ReplicationManager(
            host=host, port=port, replica_addresses=replica_addresses or [], db=self.db
        )

        self.cluster_nodes = cluster_nodes or []
        self.alive_nodes = set()

    def CreateAccount(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """
        Handle account creation requests.

        If this server is not the leader, forwards the request to the leader.
        Otherwise, creates the account locally and replicates to followers.

        Args:
            request (chat_pb2.ChatMessage): The account creation request
            context (grpc.ServicerContext): gRPC request context

        Returns:
            chat_pb2.ChatMessage: Response indicating success or failure
        """
        self.logger.debug("role is: %s", self.replication_manager.role)
        # If not leader, forward the request to the leader.
        if self.replication_manager.role != ServerRole.LEADER:
            self.logger.debug("Not leader, forwarding CreateAccount request to leader")
            try:
                leader_address = (
                    f"{self.replication_manager.leader_host}:{self.replication_manager.leader_port}"
                )
                self.logger.debug(
                    "Leader information: host=%s, port=%s",
                    self.replication_manager.leader_host,
                    self.replication_manager.leader_port,
                )
                self.logger.debug(
                    "Attempting to forward CreateAccount request to leader at %s", leader_address
                )
                channel = grpc.insecure_channel(leader_address)
                stub = chat_pb2_grpc.ChatServerStub(channel)
                response = stub.CreateAccount(request, timeout=5.0)
                self.logger.debug("Received response from leader: %s", response)
                channel.close()
                return response
            except Exception as e:
                self.logger.error("Failed to forward CreateAccount to leader: %s", e)
                return chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.ERROR,
                    payload=ParseDict({"text": f"Failed to forward to leader: {e}"}, Struct()),
                    timestamp=time.time(),
                )

        # Leader branch: Create account locally.
        username = request.sender
        if self.db.user_exists(username):
            self.logger.debug("Account for '%s' already exists.", username)
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({"text": "Username already exists"}, Struct()),
                timestamp=time.time(),
            )

        self.logger.debug("Creating account for '%s' locally as leader.", username)
        if not self.db.create_account(username, ""):
            self.logger.error("Failed to create account for '%s' locally.", username)
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({"text": "Failed to create account locally"}, Struct()),
                timestamp=time.time(),
            )

        # Replicate to followers.
        self.logger.debug("Starting replication to followers for account creation.")
        if not self.replication_manager.replicate_account(username):
            self.logger.error("Failed to replicate account creation.")
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({"text": "Failed to replicate account creation"}, Struct()),
                timestamp=time.time(),
            )
        self.logger.debug("Finished replication to followers.")

        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict({"text": "Account created successfully"}, Struct()),
            timestamp=time.time(),
        )

    def Login(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """
        Handle login requests.

        Verifies user credentials and manages login state. If the account
        doesn't exist, returns an error suggesting account creation.

        Args:
            request (chat_pb2.ChatMessage): The login request
            context (grpc.ServicerContext): gRPC request context

        Returns:
            chat_pb2.ChatMessage: Response indicating success or failure
        """
        self.logger.debug("Login request received from: %s", request.sender)
        start_time = time.time()
        username = request.sender

        # If the account does not exist, return an error response so the UI can prompt sign-up.
        if not self.db.user_exists(username):
            self.logger.debug("User does not exist. Returning error to prompt sign-up.")
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict(
                    {
                        "text": "User does not exist. Account will be created automatically. Please set a password."
                    },
                    Struct(),
                ),
                timestamp=time.time(),
            )

        self.logger.debug(
            "DB check completed in %.6f seconds. User exists.", time.time() - start_time
        )
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict({"text": "Login successful"}, Struct()),
            timestamp=time.time(),
        )

    def SendMessage(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """
        Handle message sending requests.

        If this server is not the leader, forwards the request to the leader.
        Otherwise, stores the message locally, replicates to followers, and
        delivers to active recipients.

        Args:
            request (chat_pb2.ChatMessage): The message send request
            context (grpc.ServicerContext): gRPC request context

        Returns:
            chat_pb2.ChatMessage: Response indicating success or failure
        """
        sender = request.sender
        recipient = request.recipient
        content = MessageToDict(request.payload).get("text", "")

        if not self.db.user_exists(recipient):
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({"text": "Recipient does not exist"}, Struct()),
                timestamp=time.time(),
            )

        # Check if we're the leader
        if self.replication_manager.role != ServerRole.LEADER:
            try:
                # Get current leader information
                leader_host = self.replication_manager.leader_host
                leader_port = self.replication_manager.leader_port

                if not leader_host or not leader_port:
                    return chat_pb2.ChatMessage(
                        type=chat_pb2.MessageType.ERROR,
                        payload=ParseDict(
                            {
                                "text": "No leader available. The system is currently electing a new leader. Please try again in a few seconds."
                            },
                            Struct(),
                        ),
                        timestamp=time.time(),
                    )

                # Forward the request to the leader
                channel = grpc.insecure_channel(f"{leader_host}:{leader_port}")
                stub = chat_pb2_grpc.ChatServerStub(channel)
                try:
                    response = stub.SendMessage(request, timeout=2.0)  # 2 second timeout
                    channel.close()
                    return response
                except grpc.RpcError as e:
                    channel.close()
                    # If we can't reach the leader, trigger a new election
                    self.replication_manager.last_leader_contact = 0  # Force election timeout
                    return chat_pb2.ChatMessage(
                        type=chat_pb2.MessageType.ERROR,
                        payload=ParseDict(
                            {
                                "text": "Leader unavailable. A new leader will be elected. Please try again in a few seconds."
                            },
                            Struct(),
                        ),
                        timestamp=time.time(),
                    )
            except Exception as e:
                return chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.ERROR,
                    payload=ParseDict(
                        {"text": f"Failed to forward message to leader: {str(e)}"}, Struct()
                    ),
                    timestamp=time.time(),
                )

        # We are the leader, process the message
        message_id = self.db.store_message(
            sender=sender, recipient=recipient, content=content, is_delivered=False
        )
        if message_id is None:
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({"text": "Failed to store message"}, Struct()),
                timestamp=time.time(),
            )

        # Try to replicate the message
        if not self.replication_manager.replicate_message(
            message_id=message_id, sender=sender, recipient=recipient, content=content
        ):
            # If replication fails, delete the message and step down as leader
            self.db.delete_message(message_id)
            self.replication_manager.role = ServerRole.FOLLOWER
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict(
                    {
                        "text": "Failed to replicate message. A new leader will be elected. Please try again in a few seconds."
                    },
                    Struct(),
                ),
                timestamp=time.time(),
            )

        # Deliver the message to active users
        with self.lock:
            if recipient in self.active_users:
                message = chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.SEND_MESSAGE,
                    sender=sender,
                    recipient=recipient,
                    payload=ParseDict({"text": content, "id": message_id}, Struct()),
                    timestamp=time.time(),
                )
                for q in self.active_users[recipient]:
                    try:
                        q.put(message)
                        self.db.mark_message_as_delivered(message_id)
                    except Exception as e:
                        self.logger.error("Failed to deliver message to subscriber queue: %s", e)

        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict({"text": "Message sent successfully"}, Struct()),
            timestamp=time.time(),
        )

    def Subscribe(self, request: chat_pb2.ChatMessage, context) -> None:
        """
        Handle client subscription requests for real-time messages.

        Maintains a queue of messages for each active user and delivers
        messages as they arrive. The connection is maintained until the
        client disconnects or the context is cancelled.

        Args:
            request (chat_pb2.ChatMessage): The subscription request
            context: gRPC request context
        """
        username = request.sender
        if not self.db.user_exists(username):
            return
        with self.lock:
            if username not in self.active_users:
                self.active_users[username] = set()
            self.active_users[username].add(context.peer())
        try:
            while context.is_active():
                time.sleep(1)
        except Exception as e:
            self.logger.error("Subscription error: %s", e)
        finally:
            with self.lock:
                if username in self.active_users:
                    self.active_users[username].remove(context.peer())
                    if not self.active_users[username]:
                        del self.active_users[username]

    def HandleReplication(
        self, request: chat_pb2.ReplicationMessage, context
    ) -> chat_pb2.ReplicationMessage:
        """
        Handle replication-related messages between servers.

        Processes various types of replication messages:
        - Account replication
        - Message replication
        - Vote requests
        - Heartbeats

        Args:
            request (chat_pb2.ReplicationMessage): The replication request
            context: gRPC request context

        Returns:
            chat_pb2.ReplicationMessage: Response to the replication request
        """
        if request.type == chat_pb2.ReplicationType.REPLICATE_ACCOUNT:
            username = request.account_replication.username
            # If the account already exists, consider the replication successful.
            if self.db.user_exists(username):
                success = True
            else:
                success = self.db.create_account(username, "")
            return chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATION_RESPONSE,
                term=self.replication_manager.term,
                server_id=f"{self.host}:{self.port}",
                replication_response=chat_pb2.ReplicationResponse(success=success, message_id=0),
                timestamp=time.time(),
            )

        else:
            return self.replication_manager.handle_replication_message(request)

    def GetMessages(self, request: chat_pb2.ChatMessage, context) -> chat_pb2.ChatMessage:
        username = request.sender
        messages = self.db.get_messages(username)
        if not messages:
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                payload=ParseDict({"text": "No messages found"}, Struct()),
                timestamp=time.time(),
            )
        formatted_messages = []
        for msg in messages:
            formatted_messages.append(
                f"From: {msg['sender']}\n"
                f"Content: {msg['content']}\n"
                f"Time: {time.ctime(msg['timestamp'])}\n"
                f"{'(Delivered)' if msg['is_delivered'] else '(Pending)'}\n"
            )
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict({"text": "\n".join(formatted_messages)}, Struct()),
            timestamp=time.time(),
        )

    def RequestVote(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        payload = MessageToDict(request.payload)
        term = payload.get("term", 0)
        candidate_id = request.sender
        vote_granted = self.replication_manager.handle_vote_request(term, candidate_id)
        response_payload = {"vote_granted": vote_granted}
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=candidate_id,
            timestamp=time.time(),
        )

    def Heartbeat(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        payload = MessageToDict(request.payload)
        term = payload.get("term", 0)
        leader_id = request.sender
        self.replication_manager.handle_heartbeat(term, leader_id)
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=Struct(),
            sender="SERVER",
            recipient=leader_id,
            timestamp=time.time(),
        )

    def ReplicateMessage(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        payload = MessageToDict(request.payload)
        if self.replication_manager.handle_replicate_message(payload):
            message_id = payload.get("message_id")
            sender = payload.get("sender")
            recipient = payload.get("recipient")
            content = payload.get("text")
            delivered = recipient in self.active_users
            stored_id = self.db.store_message(sender, recipient, content, delivered)
            if stored_id == message_id:
                if delivered:
                    try:
                        new_msg = chat_pb2.ChatMessage(
                            type=chat_pb2.MessageType.SEND_MESSAGE,
                            payload=ParseDict({"text": content}, Struct()),
                            sender=sender,
                            recipient=recipient,
                            timestamp=time.time(),
                        )
                        self.active_users[recipient].add(context.peer())
                        self.db.mark_message_as_delivered(message_id)
                    except Exception as e:
                        self.logger.error(f"Failed to deliver replicated message: {e}")
                return chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.SUCCESS,
                    payload=Struct(),
                    sender="SERVER",
                    recipient=request.sender,
                    timestamp=time.time(),
                )
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.ERROR,
            payload=Struct(),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )

    def ReadMessages(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext):
        username = request.recipient
        q = queue.Queue()
        with self.lock:
            # Register the new queue for this user.
            if username not in self.active_users:
                self.active_users[username] = []
            self.active_users[username].append(q)
        try:
            # First yield any undelivered messages.
            undelivered = self.db.get_undelivered_messages(username)
            for msg in undelivered:
                try:
                    timestamp_val = float(msg.get("timestamp", time.time()))
                except Exception:
                    timestamp_val = time.time()
                response_payload = {"text": msg["content"], "id": msg["id"]}
                parsed_payload = ParseDict(response_payload, Struct())
                chat_msg = chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.SEND_MESSAGE,
                    payload=parsed_payload,
                    sender=msg["sender"],
                    recipient=username,
                    timestamp=timestamp_val,
                )
                yield chat_msg
                self.db.mark_message_as_delivered(msg["id"])

            # Now wait for new messages.
            while True:
                try:
                    message = q.get(timeout=60)
                    yield message
                except queue.Empty:
                    if context.is_active():
                        continue
                    else:
                        break
        finally:
            with self.lock:
                if username in self.active_users and q in self.active_users[username]:
                    self.active_users[username].remove(q)
                    if not self.active_users[username]:
                        del self.active_users[username]

    def ListAccounts(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        start_deser = time.perf_counter()
        payload = MessageToDict(request.payload)
        end_deser = time.perf_counter()
        self.logger.info(
            f"[ListAccounts] Deserialization took {end_deser - start_deser:.6f} seconds"
        )

        pattern = payload.get("pattern", "")
        page = int(payload.get("page", 1))
        per_page = 10
        result = self.db.list_accounts(pattern, page, per_page)

        start_ser = time.perf_counter()
        parsed_payload = ParseDict(result, Struct())
        end_ser = time.perf_counter()
        self.logger.info(f"[ListAccounts] Serialization took {end_ser - start_ser:.6f} seconds")

        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=parsed_payload,
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )
        return response

    def DeleteMessages(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        start_deser = time.perf_counter()
        payload = MessageToDict(request.payload)
        end_deser = time.perf_counter()
        self.logger.info(
            f"[DeleteMessages] Deserialization took {end_deser - start_deser:.6f} seconds"
        )
        message_ids = payload.get("message_ids", [])
        if not isinstance(message_ids, list):
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("'message_ids' must be a list.")
            return chat_pb2.ChatMessage()
        success = self.db.delete_messages(request.sender, message_ids)
        if success:
            response_payload = {"text": "Messages deleted successfully."}
            msg_type = chat_pb2.MessageType.SUCCESS
        else:
            response_payload = {"text": "Failed to delete messages."}
            msg_type = chat_pb2.MessageType.ERROR
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(response_payload, Struct())
        end_ser = time.perf_counter()
        self.logger.info(f"[DeleteMessages] Serialization took {end_ser - start_ser:.6f} seconds")
        response = chat_pb2.ChatMessage(
            type=msg_type,
            payload=parsed_payload,
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )
        if success:
            # Replicate deletion to followers:
            message_ids = [int(mid) for mid in message_ids]
            deletion_payload = {"message_ids": message_ids, "username": request.sender}
            replication_request = chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATE_DELETE_MESSAGES,
                term=self.replication_manager.term,
                server_id=f"{self.host}:{self.port}",
                deletion=ParseDict(deletion_payload, chat_pb2.DeletionPayload()),
                timestamp=time.time(),
            )
            if not self.replication_manager.replicate_operation(replication_request):
                self.logger.warning("Failed to replicate message deletion.")
                return response
        return response

    def DeleteAccount(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        username = request.sender
        if self.db.delete_account(username):
            # Replicate account deletion to followers:
            replication_request = chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATE_DELETE_ACCOUNT,
                term=self.replication_manager.term,
                server_id=f"{self.host}:{self.port}",
                deletion=ParseDict({"username": username}, chat_pb2.DeletionPayload()),
                timestamp=time.time(),
            )
            if not self.replication_manager.replicate_operation(replication_request):
                self.logger.warning("Failed to replicate account deletion.")
            response_payload = {"text": "Account deleted successfully."}
            start_ser = time.perf_counter()
            parsed_payload = ParseDict(response_payload, Struct())
            end_ser = time.perf_counter()
            self.logger.info(
                f"[DeleteAccount] Serialization took {end_ser - start_ser:.6f} seconds"
            )
            response = chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                payload=parsed_payload,
                sender="SERVER",
                recipient=username,
                timestamp=time.time(),
            )
            return response
        else:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Failed to delete account.")
            return chat_pb2.ChatMessage()

    def ListChatPartners(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        username = request.sender
        partners = self.db.get_chat_partners(username)
        unread_map = {}
        for p in partners:
            unread_map[p] = self.db.get_unread_between_users(username, p)
        response_payload = {"chat_partners": partners, "unread_map": unread_map}
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(response_payload, Struct())
        end_ser = time.perf_counter()
        self.logger.info(f"[ListChatPartners] Serialization took {end_ser - start_ser:.6f} seconds")
        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=parsed_payload,
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )
        return response

    def ReadConversation(self, request, context):
        start_deser = time.perf_counter()
        payload = MessageToDict(request.payload)
        end_deser = time.perf_counter()
        self.logger.info(
            f"[ReadConversation] Deserialization took {end_deser - start_deser:.6f} seconds"
        )
        partner = payload.get("partner")
        offset = int(payload.get("offset", 0))
        limit = int(payload.get("limit", 50))
        username = request.sender
        conversation = self.db.get_messages_between_users(username, partner, offset, limit)
        response_payload = {
            "messages": conversation.get("messages", []),
            "total": conversation.get("total", 0),
        }
        start_ser = time.perf_counter()
        parsed_payload = ParseDict(response_payload, Struct())
        end_ser = time.perf_counter()
        self.logger.info(f"[ReadConversation] Serialization took {end_ser - start_ser:.6f} seconds")
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=parsed_payload,
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )

    def GetLeader(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        if self.replication_manager.leader_host and self.replication_manager.leader_port:
            leader_address = (
                f"{self.replication_manager.leader_host}:{self.replication_manager.leader_port}"
            )
        else:
            leader_address = "Unknown"
        # logging.debug("GetLeader called. Returning leader: %s", leader_address)
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict({"leader": leader_address}, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )

    def MarkRead(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        if self.replication_manager.role != ServerRole.LEADER:
            # 1. Forward to leader
            try:
                leader_address = (
                    f"{self.replication_manager.leader_host}:{self.replication_manager.leader_port}"
                )
                channel = grpc.insecure_channel(leader_address)
                stub = chat_pb2_grpc.ChatServerStub(channel)
                response = stub.MarkRead(request, timeout=5.0)
                channel.close()
                return response
            except Exception as e:
                # fallback/error message
                return chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.ERROR,
                    payload=ParseDict({"text": f"Failed to contact leader: {e}"}, Struct()),
                    timestamp=time.time(),
                )

        # Extract the list of message IDs from the payload.
        payload = MessageToDict(request.payload)
        message_ids = payload.get("message_ids", [])
        username = request.sender
        if not isinstance(message_ids, list):
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("'message_ids' must be a list.")
            return chat_pb2.ChatMessage()
        # Call the DatabaseManager method to mark messages as read.
        success = self.db.mark_messages_as_read(username, message_ids)
        response_payload = (
            {"text": "Read status updated successfully."}
            if success
            else {"text": "Failed to update read status."}
        )
        response_type = chat_pb2.MessageType.SUCCESS if success else chat_pb2.MessageType.ERROR
        if success:
            # Ensure all message IDs are integers
            message_ids_int = [int(mid) for mid in message_ids]
            replication_request = chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATE_MARK_READ,
                term=self.replication_manager.term,
                server_id=f"{self.host}:{self.port}",
                deletion=ParseDict(
                    {"username": request.sender, "message_ids": message_ids_int},
                    chat_pb2.DeletionPayload(),
                ),
                timestamp=time.time(),
            )
            if not self.replication_manager.replicate_operation(replication_request):
                self.logger.warning("Failed to replicate mark read operation.")

        return chat_pb2.ChatMessage(
            type=response_type,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )

    def heartbeat_from_node(self, host, port):
        """
        Called when a node sends a heartbeat, marking it alive.
        """
        self.alive_nodes.add((host, port))

    def mark_node_dead(self, host, port):
        """
        Called if we haven't heard from a node in a while.
        """
        if (host, port) in self.alive_nodes:
            self.alive_nodes.remove((host, port))

    def GetClusterNodes(self, request, context):
        """
        Return the current cluster membership as a list of "host:port" strings,
        but only include nodes that are known to be alive.
        """
        # Filter the complete cluster membership against the set of alive nodes.
        active_nodes = [
            f"{host}:{port}"
            for (host, port) in self.cluster_nodes
            if (host, port) in self.alive_nodes
        ]
        payload_dict = {"nodes": active_nodes}
        payload_struct = ParseDict(payload_dict, Struct())
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.GET_CLUSTER_NODES,
            payload=payload_struct,
            sender="SERVER",
            recipient=request.sender,  # or "SERVER" if you prefer
            timestamp=time.time(),
        )


def serve(host: str, port: int) -> None:
    server_logger.info("Starting gRPC server on %s:%s...", host, port)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServerServicer_to_server(ChatServer(), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    server_logger.info("Server started. Waiting for termination...")
    server.wait_for_termination()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the gRPC Chat Server")
    parser.add_argument(
        "--host", type=str, default="[::]", help="Host to bind the gRPC server on (default: [::])"
    )
    parser.add_argument(
        "--port", type=int, default=50051, help="Port to bind the gRPC server on (default: 50051)"
    )
    parser.add_argument(
        "--replicas",
        nargs="+",
        default=[],
        help="List of replica addresses (e.g., 127.0.0.1:50052 127.0.0.1:50053)",
    )
    parser.add_argument(
        "--db_path", type=str, help="Path to database file (default: chat_<port>.db)"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level (default: INFO)",
    )
    parser.add_argument(
        "--heartbeat-log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="WARNING",
        help="Set the heartbeat logging level (default: WARNING)",
    )
    args = parser.parse_args()

    # Set log levels based on command line arguments
    server_logger.setLevel(getattr(logging, args.log_level))
    heartbeat_logger.setLevel(getattr(logging, args.heartbeat_log_level))

    server_logger.info(
        "Starting gRPC server on %s:%s with replicas: %s", args.host, args.port, args.replicas
    )
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServerServicer_to_server(
        ChatServer(
            host=args.host, port=args.port, db_path=args.db_path, replica_addresses=args.replicas
        ),
        server,
    )
    server.add_insecure_port(f"{args.host}:{args.port}")
    server.start()
    server_logger.info("Server started. Waiting for termination...")
    server.wait_for_termination()
