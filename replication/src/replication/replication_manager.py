import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
import random

from src.protocols.grpc import chat_pb2, chat_pb2_grpc
import logging

logging.basicConfig(level=logging.DEBUG)


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

        # Separate locks for different state components
        self.role_lock = threading.Lock()
        self.term_lock = threading.Lock()
        self.vote_lock = threading.Lock()
        self.leader_lock = threading.Lock()
        self.replica_lock = threading.Lock()

        self.commit_index = 0
        self.last_log_index = 0
        self.last_log_term = 0
        self.election_in_progress = False
        self.last_leader_contact = time.time()

        # Configuration constants
        self.HEARTBEAT_INTERVAL = 0.1  # 100ms between heartbeats
        self.MIN_ELECTION_TIMEOUT = 1.0  # Minimum election timeout 1 second
        self.MAX_ELECTION_TIMEOUT = 2.0  # Maximum election timeout 2 seconds

        # Parse and store replica addresses
        for addr in replica_addresses:
            if addr:
                host, port = addr.split(":")
                if host != self.host or int(port) != self.port:  # Don't add self
                    with self.replica_lock:
                        self.replicas[addr] = ReplicaInfo(host=host, port=int(port))

        # Start election timeout thread
        self.election_timeout = threading.Event()
        self.election_thread = threading.Thread(target=self._run_election_timer, daemon=True)
        self.election_thread.start()

        # Start heartbeat thread
        self.heartbeat_thread = threading.Thread(target=self._send_heartbeats, daemon=True)
        self.heartbeat_thread.start()

        logging.info(
            f"Server started at {self.host}:{self.port} with {len(self.replicas)} replicas"
        )

    def _run_election_timer(self) -> None:
        """Run the election timeout loop with randomized timeouts"""
        while True:
            # Randomized election timeout between MIN and MAX timeout values
            # This randomization helps prevent split votes
            timeout = random.uniform(self.MIN_ELECTION_TIMEOUT, self.MAX_ELECTION_TIMEOUT)

            if self.election_timeout.wait(timeout):
                self.election_timeout.clear()
                continue

            # Only start election if:
            # 1. We're a follower
            # 2. No election is in progress
            # 3. Haven't heard from leader for longer than timeout
            with self.role_lock:
                current_role = self.role

            time_since_leader = time.time() - self.last_leader_contact

            if (
                current_role == ServerRole.FOLLOWER
                and not self.election_in_progress
                and time_since_leader > timeout
            ):
                logging.info(
                    f"Haven't heard from leader for {time_since_leader:.2f}s (timeout was {timeout:.2f}s), starting election"
                )
                self._start_election()

    def _start_election(self) -> None:
        """Start a new election following Raft protocol"""
        with self.role_lock:
            if self.election_in_progress:
                return

            self.election_in_progress = True
            self.role = ServerRole.CANDIDATE

        with self.term_lock:
            self.term += 1
            current_term = self.term

        with self.vote_lock:
            self.voted_for = f"{self.host}:{self.port}"
            votes = 1

        logging.debug(f"Starting election for term {current_term}")

        with self.replica_lock:
            replicas = list(self.replicas.items())

        for addr, replica in replicas:
            try:
                channel = grpc.insecure_channel(f"{replica.host}:{replica.port}")
                stub = chat_pb2_grpc.ChatServerStub(channel)

                vote_request = chat_pb2.VoteRequest(
                    last_log_term=self.last_log_term, last_log_index=self.last_log_index
                )

                request = chat_pb2.ReplicationMessage(
                    type=chat_pb2.ReplicationType.REQUEST_VOTE,
                    term=current_term,
                    server_id=f"{self.host}:{self.port}",
                    vote_request=vote_request,
                    timestamp=time.time(),
                )

                response = stub.HandleReplication(request)

                with self.role_lock:
                    current_role = self.role

                with self.term_lock:
                    if response.term > self.term:
                        self.term = response.term
                        with self.role_lock:
                            self.role = ServerRole.FOLLOWER
                        with self.vote_lock:
                            self.voted_for = None
                        self.election_in_progress = False
                        logging.info(f"Stepping down - discovered higher term {response.term}")
                        return

                    if (
                        current_role == ServerRole.CANDIDATE
                        and self.term == current_term
                        and response.type == chat_pb2.ReplicationType.VOTE_RESPONSE
                        and response.vote_response.vote_granted
                    ):
                        votes += 1
                        logging.debug(f"Vote granted from {addr}")

            except Exception as e:
                logging.error(f"Failed to request vote from {addr}: {e}")

        with self.role_lock:
            if self.role == ServerRole.CANDIDATE:
                if votes > (len(self.replicas) + 1) / 2:
                    self.role = ServerRole.LEADER
                    with self.leader_lock:
                        self.leader_host = self.host
                        self.leader_port = self.port
                    logging.info(f"Elected as leader for term {current_term}")
                    self._send_initial_heartbeat()
                else:
                    self.role = ServerRole.FOLLOWER
                    logging.info(
                        f"Election failed. Returning to follower state. Term: {current_term}"
                    )

        self.election_in_progress = False

    def _send_initial_heartbeat(self) -> None:
        """Send immediate heartbeat to all followers after becoming leader"""
        if self.role != ServerRole.LEADER:
            return

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
                logging.error(f"Failed to send initial heartbeat to {addr}: {e}")
                replica.is_alive = False

    def _send_heartbeats(self) -> None:
        """Send heartbeats to all followers if we're the leader"""
        while True:
            if self.role == ServerRole.LEADER:
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
                        logging.debug(f"Heartbeat sent to {addr} successfully.")
                    except Exception as e:
                        logging.error(f"Failed to send heartbeat to {addr}: {e}")
                        replica.is_alive = False
            time.sleep(self.HEARTBEAT_INTERVAL)  # Sleep for heartbeat interval

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
        with self.term_lock:
            if message.term > self.term:
                self.term = message.term
                with self.role_lock:
                    self.role = ServerRole.FOLLOWER
                with self.vote_lock:
                    self.voted_for = None
                self.election_in_progress = False
                self.last_leader_contact = time.time()

            if message.term < self.term:
                return chat_pb2.ReplicationMessage(
                    type=chat_pb2.ReplicationType.REPLICATION_ERROR,
                    term=self.term,
                    server_id=f"{self.host}:{self.port}",
                    timestamp=time.time(),
                )

        if message.type == chat_pb2.ReplicationType.REQUEST_VOTE:
            with self.vote_lock:
                vote_granted = False
                if self.voted_for is None or self.voted_for == message.server_id:
                    candidate_log_ok = message.vote_request.last_log_term > self.last_log_term or (
                        message.vote_request.last_log_term == self.last_log_term
                        and message.vote_request.last_log_index >= self.last_log_index
                    )
                    if candidate_log_ok:
                        vote_granted = True
                        self.voted_for = message.server_id
                        self.election_timeout.set()
                        self.last_leader_contact = time.time()

            return chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.VOTE_RESPONSE,
                term=self.term,
                server_id=f"{self.host}:{self.port}",
                vote_response=chat_pb2.VoteResponse(vote_granted=vote_granted),
                timestamp=time.time(),
            )

        elif message.type == chat_pb2.ReplicationType.HEARTBEAT:
            with self.role_lock:
                if self.term == message.term and self.role != ServerRole.FOLLOWER:
                    self.role = ServerRole.FOLLOWER
                    with self.vote_lock:
                        self.voted_for = None

            self.election_timeout.set()
            self.last_leader_contact = time.time()

            with self.leader_lock:
                self.leader_host, self.leader_port = message.server_id.split(":")
                self.leader_port = int(self.leader_port)

            return chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATION_SUCCESS,
                term=self.term,
                server_id=f"{self.host}:{self.port}",
                timestamp=time.time(),
            )

        elif message.type == chat_pb2.ReplicationType.REPLICATE_MESSAGE:
            if message.term == self.term:
                self.last_leader_contact = time.time()

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
