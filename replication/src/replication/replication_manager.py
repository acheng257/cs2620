import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

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
            timeout = random.uniform(0.3, 0.5)  # 300–500ms
            if self.election_timeout.wait(timeout):
                self.election_timeout.clear()
                continue
            if self.role != ServerRole.LEADER:
                self._start_election()

    def _start_election(self) -> None:
        with self.lock:
            self.term += 1
            self.role = ServerRole.CANDIDATE
            self.voted_for = f"{self.host}:{self.port}"
            votes = 1  # Vote for self
            logging.debug(f"Starting election for term {self.term} from {self.host}:{self.port}")
            logging.debug(f"Current replicas: {self.replicas}")

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
                    if (response.type == chat_pb2.ReplicationType.VOTE_RESPONSE and 
                        response.vote_response.vote_granted):
                        votes += 1
                        logging.debug(f"Vote granted from {addr}")
                    channel.close()
                except Exception as e:
                    logging.error(f"Failed to request vote from {addr}: {e}")

            logging.debug(f"Election votes received: {votes}")
            if votes > (len(self.replicas) + 1) / 2:
                self.role = ServerRole.LEADER
                self.leader_host = self.host
                self.leader_port = self.port
                logging.info(f"Elected as leader: {self.host}:{self.port} for term {self.term}")
                self._start_heartbeat()
            else:
                self.role = ServerRole.FOLLOWER
                logging.info(f"Election failed. Remains follower. Current term: {self.term}")


    def _start_heartbeat(self) -> None:
        if self.heartbeat_thread is None:
            self.heartbeat_thread = threading.Thread(target=self._send_heartbeats, daemon=True)
            self.heartbeat_thread.start()

    def _send_heartbeats(self) -> None:
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
                    channel.close()
                except Exception as e:
                    logging.error(f"Failed to send heartbeat to {addr}: {e}")
                    replica.is_alive = False
            time.sleep(0.05)

    def replicate_account(self, username: str) -> bool:
        """
        Replicate account creation to all followers and wait for majority acknowledgment.
        Returns True if the account creation was replicated to a majority of followers.
        """
        if self.role != ServerRole.LEADER:
            logging.error("Attempt to replicate account on a non-leader server.")
            return False

        acks = 1  # Count self
        account_replication = chat_pb2.AccountReplication(username=username)
        request = chat_pb2.ReplicationMessage(
            type=chat_pb2.ReplicationType.REPLICATE_ACCOUNT,
            term=self.term,
            server_id=f"{self.host}:{self.port}",
            account_replication=account_replication,
            timestamp=time.time(),
        )
        logging.debug(f"Replicating account creation for '{username}' to followers. Request: {request}")

        for addr, replica in self.replicas.items():
            if not replica.is_alive:
                logging.info(f"Skipping replica {addr} because it is marked not alive.")
                continue
            try:
                logging.debug(f"Creating channel to replica {addr} at {replica.host}:{replica.port}.")
                channel = grpc.insecure_channel(f"{replica.host}:{replica.port}")
                stub = chat_pb2_grpc.ChatServerStub(channel)
                logging.debug(f"Sending replication request to {addr} with 1.0s timeout.")
                start_time = time.time()
                response = stub.HandleReplication(request, timeout=1.0)
                duration = time.time() - start_time
                logging.debug(f"Received response from {addr} in {duration:.3f}s: {response}")
                channel.close()
                if (response.type == chat_pb2.ReplicationType.REPLICATION_RESPONSE and 
                    response.replication_response.success):
                    acks += 1
                    logging.debug(f"Account replication acknowledged from {addr}.")
                else:
                    logging.error(f"Account replication from {addr} returned failure: {response}")
            except Exception as e:
                logging.exception(f"Failed to replicate account to {addr}: {e}")
                continue

        logging.info(f"Total acknowledgments received: {acks} (including self).")
        success = acks > (len(self.replicas) + 1) / 2
        if success:
            logging.info(f"Account '{username}' replicated successfully with {acks} acks.")
        else:
            logging.error(f"Account '{username}' replication failed. Acks: {acks}")
        return success

    def handle_replication_message(self, message: chat_pb2.ReplicationMessage) -> chat_pb2.ReplicationMessage:
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
            # For simplicity, assume message replication always succeeds.
            msg_id = message.message_replication.message_id
            return chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATION_RESPONSE,
                term=self.term,
                server_id=f"{self.host}:{self.port}",
                replication_response=chat_pb2.ReplicationResponse(success=True, message_id=msg_id),
                timestamp=time.time(),
            )

        return chat_pb2.ReplicationMessage(
            type=chat_pb2.ReplicationType.REPLICATION_ERROR,
            term=self.term,
            server_id=f"{self.host}:{self.port}",
            timestamp=time.time(),
        )
