import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

from src.protocols.grpc import chat_pb2, chat_pb2_grpc


class ServerRole(Enum):
    LEADER = "leader"
    FOLLOWER = "follower"
    CANDIDATE = "candidate"


@dataclass
class ReplicaInfo:
    """Information about a replica in the system"""

    host: str
    port: int
    is_alive: bool = True
    last_heartbeat: float = time.time()


class ReplicationManager:
    """
    Manages replication between leader and follower servers.
    Implements a basic leader-follower protocol with majority acknowledgment.
    """

    def __init__(self, host: str, port: int, replica_addresses: List[str]) -> None:
        """
        Initialize the replication manager.

        Args:
            host: The host address of this server
            port: The port of this server
            replica_addresses: List of "host:port" strings for all replicas
        """
        self.host = host
        self.port = port
        self.role = ServerRole.FOLLOWER
        self.leader_host: Optional[str] = None
        self.leader_port: Optional[int] = None
        self.term = 0
        self.voted_for: Optional[str] = None
        self.replicas: Dict[str, ReplicaInfo] = {}
        self.lock = threading.Lock()
        self.commit_index = 0
        self.last_log_index = 0
        self.last_log_term = 0

        # Parse and store replica addresses
        for addr in replica_addresses:
            if addr:
                host, port = addr.split(":")
                if host != self.host or int(port) != self.port:  # Don't add self
                    self.replicas[addr] = ReplicaInfo(host=host, port=int(port))

        # Start election timeout thread
        self.election_timeout = threading.Event()
        self.election_thread = threading.Thread(target=self._run_election_timer, daemon=True)
        self.election_thread.start()

        # Start heartbeat thread if leader
        self.heartbeat_thread: Optional[threading.Thread] = None
        if self.role == ServerRole.LEADER:
            self._start_heartbeat()

    def _run_election_timer(self) -> None:
        """Run the election timeout loop"""
        while True:
            # Random timeout between 150-300ms
            timeout = 0.15 + (hash(str(time.time())) % 150) / 1000
            if self.election_timeout.wait(timeout):
                self.election_timeout.clear()
                continue

            if self.role != ServerRole.LEADER:
                self._start_election()

    def _start_election(self) -> None:
        """Start a new leader election"""
        with self.lock:
            self.term += 1
            self.role = ServerRole.CANDIDATE
            self.voted_for = f"{self.host}:{self.port}"
            votes = 1  # Vote for self

            # Request votes from all replicas
            for addr, replica in self.replicas.items():
                try:
                    channel = grpc.insecure_channel(f"{replica.host}:{replica.port}")
                    stub = chat_pb2_grpc.ChatServerStub(channel)

                    vote_request = chat_pb2.VoteRequest(
                        last_log_term=self.last_log_term, last_log_index=self.last_log_index
                    )

                    request = chat_pb2.ReplicationMessage(
                        type=chat_pb2.ReplicationType.REQUEST_VOTE,
                        term=self.term,
                        server_id=f"{self.host}:{self.port}",
                        vote_request=vote_request,
                        timestamp=time.time(),
                    )

                    response = stub.HandleReplication(request)
                    if (
                        response.type == chat_pb2.ReplicationType.VOTE_RESPONSE
                        and response.vote_response.vote_granted
                    ):
                        votes += 1

                except Exception as e:
                    print(f"Failed to request vote from {addr}: {e}")
                    continue

            # If received majority votes, become leader
            if votes > (len(self.replicas) + 1) / 2:
                self.role = ServerRole.LEADER
                self.leader_host = self.host
                self.leader_port = self.port
                self._start_heartbeat()
            else:
                self.role = ServerRole.FOLLOWER

    def _start_heartbeat(self) -> None:
        """Start sending heartbeats to followers"""
        if self.heartbeat_thread is None:
            self.heartbeat_thread = threading.Thread(target=self._send_heartbeats, daemon=True)
            self.heartbeat_thread.start()

    def _send_heartbeats(self) -> None:
        """Send periodic heartbeats to all followers"""
        while self.role == ServerRole.LEADER:
            for addr, replica in self.replicas.items():
                try:
                    channel = grpc.insecure_channel(f"{replica.host}:{replica.port}")
                    stub = chat_pb2_grpc.ChatServerStub(channel)

                    heartbeat = chat_pb2.Heartbeat(commit_index=self.commit_index)
                    request = chat_pb2.ReplicationMessage(
                        type=chat_pb2.ReplicationType.HEARTBEAT,
                        term=self.term,
                        server_id=f"{self.host}:{self.port}",
                        heartbeat=heartbeat,
                        timestamp=time.time(),
                    )

                    response = stub.HandleReplication(request)
                    replica.is_alive = True
                    replica.last_heartbeat = time.time()

                except Exception as e:
                    print(f"Failed to send heartbeat to {addr}: {e}")
                    replica.is_alive = False
                    continue

            time.sleep(0.05)  # 50ms heartbeat interval

    def replicate_message(self, message_id: int, sender: str, recipient: str, content: str) -> bool:
        """
        Replicate a message to all followers and wait for majority acknowledgment.

        Returns:
            bool: True if message was replicated to a majority of followers
        """
        if self.role != ServerRole.LEADER:
            return False

        acks = 1  # Count self
        message_replication = chat_pb2.MessageReplication(
            message_id=message_id, sender=sender, recipient=recipient, content=content
        )

        request = chat_pb2.ReplicationMessage(
            type=chat_pb2.ReplicationType.REPLICATE_MESSAGE,
            term=self.term,
            server_id=f"{self.host}:{self.port}",
            message_replication=message_replication,
            timestamp=time.time(),
        )

        for addr, replica in self.replicas.items():
            if not replica.is_alive:
                continue

            try:
                channel = grpc.insecure_channel(f"{replica.host}:{replica.port}")
                stub = chat_pb2_grpc.ChatServerStub(channel)

                response = stub.HandleReplication(request)
                if (
                    response.type == chat_pb2.ReplicationType.REPLICATION_RESPONSE
                    and response.replication_response.success
                ):
                    acks += 1

            except Exception as e:
                print(f"Failed to replicate message to {addr}: {e}")
                continue

        success = acks > (len(self.replicas) + 1) / 2
        if success:
            self.last_log_index += 1
            self.last_log_term = self.term
            self.commit_index = self.last_log_index
        return success

    def handle_replication_message(
        self, message: chat_pb2.ReplicationMessage
    ) -> chat_pb2.ReplicationMessage:
        """Handle incoming replication messages from other servers"""
        if message.term < self.term:
            return chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATION_ERROR,
                term=self.term,
                server_id=f"{self.host}:{self.port}",
                timestamp=time.time(),
            )

        if message.term > self.term:
            self.term = message.term
            self.role = ServerRole.FOLLOWER
            self.voted_for = None

        if message.type == chat_pb2.ReplicationType.REQUEST_VOTE:
            vote_granted = False
            if self.voted_for is None or self.voted_for == message.server_id:
                if message.vote_request.last_log_term > self.last_log_term or (
                    message.vote_request.last_log_term == self.last_log_term
                    and message.vote_request.last_log_index >= self.last_log_index
                ):
                    vote_granted = True
                    self.voted_for = message.server_id

            return chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.VOTE_RESPONSE,
                term=self.term,
                server_id=f"{self.host}:{self.port}",
                vote_response=chat_pb2.VoteResponse(vote_granted=vote_granted),
                timestamp=time.time(),
            )

        elif message.type == chat_pb2.ReplicationType.HEARTBEAT:
            self.election_timeout.set()  # Reset election timeout
            self.leader_host, self.leader_port = message.server_id.split(":")
            self.leader_port = int(self.leader_port)

            return chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATION_SUCCESS,
                term=self.term,
                server_id=f"{self.host}:{self.port}",
                timestamp=time.time(),
            )

        elif message.type == chat_pb2.ReplicationType.REPLICATE_MESSAGE:
            success = True
            msg_id = message.message_replication.message_id

            return chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATION_RESPONSE,
                term=self.term,
                server_id=f"{self.host}:{self.port}",
                replication_response=chat_pb2.ReplicationResponse(
                    success=success, message_id=msg_id
                ),
                timestamp=time.time(),
            )

        return chat_pb2.ReplicationMessage(
            type=chat_pb2.ReplicationType.REPLICATION_ERROR,
            term=self.term,
            server_id=f"{self.host}:{self.port}",
            timestamp=time.time(),
        )
