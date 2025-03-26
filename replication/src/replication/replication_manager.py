import threading
import time
import random
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict

from src.protocols.grpc import chat_pb2, chat_pb2_grpc

logging.basicConfig(level=logging.DEBUG)


class ServerRole(Enum):
    LEADER = "leader"
    FOLLOWER = "follower"
    CANDIDATE = "candidate"


@dataclass
class ReplicaInfo:
    """Information about a replica in the system."""

    host: str
    port: int
    is_alive: bool = True
    last_heartbeat: float = time.time()


class ReplicationManager:
    """
    Manages replication between leader and follower servers.
    Implements a basic leader-follower protocol with majority acknowledgment,
    but now the 'majority' is computed from the *currently active* servers.
    """

    def __init__(self, host: str, port: int, replica_addresses: List[str], db) -> None:
        self.host = host
        self.port = port
        self.db = db  # Reference to the ChatServer's DatabaseManager

        # Start as a follower
        self.role = ServerRole.FOLLOWER

        # Leader info
        self.leader_host: Optional[str] = None
        self.leader_port: Optional[int] = None

        # Raft-like term & voting info
        self.term = 0
        self.voted_for: Optional[str] = None

        # Lock objects to protect shared state
        self.role_lock = threading.Lock()
        self.term_lock = threading.Lock()
        self.vote_lock = threading.Lock()
        self.leader_lock = threading.Lock()
        self.replica_lock = threading.Lock()

        # Raft-like replication indices
        self.commit_index = 0
        self.last_log_index = 0
        self.last_log_term = 0

        self.election_in_progress = False
        self.last_leader_contact = time.time()

        # Heartbeat & election settings
        self.HEARTBEAT_INTERVAL = 0.1        # 100ms between heartbeats
        self.MIN_ELECTION_TIMEOUT = 1.0      # Min election timeout
        self.MAX_ELECTION_TIMEOUT = 2.0      # Max election timeout

        # Dictionary of known replicas
        self.replicas: Dict[str, ReplicaInfo] = {}
        for addr in replica_addresses:
            if addr:
                h, p = addr.split(":")
                p = int(p)
                # Don't add self
                if not (h == self.host and p == self.port):
                    self.replicas[addr] = ReplicaInfo(host=h, port=p, is_alive=True)

        # Event to interrupt the election timer early
        self.election_timeout = threading.Event()

        # Start background threads
        self.election_thread = threading.Thread(target=self._run_election_timer, daemon=True)
        self.election_thread.start()

        self.heartbeat_thread = threading.Thread(target=self._send_heartbeats, daemon=True)
        self.heartbeat_thread.start()

        logging.info(
            f"Server started at {self.host}:{self.port} with {len(self.replicas)} replicas."
        )

    def _run_election_timer(self) -> None:
        """Run the election timeout loop with randomized intervals."""
        while True:
            timeout = random.uniform(self.MIN_ELECTION_TIMEOUT, self.MAX_ELECTION_TIMEOUT)

            # If the event is set within 'timeout' seconds, we skip starting an election
            if self.election_timeout.wait(timeout):
                self.election_timeout.clear()
                continue

            with self.role_lock:
                current_role = self.role
            time_since_leader = time.time() - self.last_leader_contact

            # Start election if:
            # 1) We're a follower
            # 2) No election is in progress
            # 3) Haven't heard from the leader for longer than specified timeout
            if (
                current_role == ServerRole.FOLLOWER
                and not self.election_in_progress
                and time_since_leader > timeout
            ):
                logging.info(
                    f"Haven't heard from leader for {time_since_leader:.2f}s (timeout was {timeout:.2f}s). Starting election..."
                )
                self._start_election()

    def _start_election(self) -> None:
        """Convert to candidate, increment term, and ask other servers for votes."""
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
            votes = 1  # We vote for ourselves

        logging.debug(f"Starting election for term {current_term}.")

        # Identify which replicas are currently alive
        with self.replica_lock:
            # We only consider "alive" replicas in the vote tally
            alive_replicas = []
            for addr, info in self.replicas.items():
                if info.is_alive:
                    alive_replicas.append((addr, info))
            alive_count = 1 + len(alive_replicas)  # plus this server
            needed_votes = (alive_count // 2) + 1
            logging.debug(
                f"Among active servers, total alive={alive_count}. Need {needed_votes} votes."
            )

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

        for addr, replica in alive_replicas:
            try:
                channel = grpc.insecure_channel(f"{replica.host}:{replica.port}")
                stub = chat_pb2_grpc.ChatServerStub(channel)

                try:
                    response = stub.HandleReplication(request, timeout=2.0)
                    channel.close()

                    # If we see a higher term, step down
                    with self.term_lock:
                        if response.term > self.term:
                            self.term = response.term
                            with self.role_lock:
                                self.role = ServerRole.FOLLOWER
                            with self.vote_lock:
                                self.voted_for = None
                            self.election_in_progress = False
                            logging.info(
                                f"Stepping down - discovered higher term {response.term} from {addr}"
                            )
                            return

                    with self.role_lock:
                        current_role = self.role
                    with self.term_lock:
                        if current_role == ServerRole.CANDIDATE and self.term == current_term:
                            # Check if vote granted
                            if (
                                response.type == chat_pb2.ReplicationType.VOTE_RESPONSE
                                and response.vote_response.vote_granted
                            ):
                                votes += 1
                                logging.debug(
                                    f"Vote granted from {addr}, total votes={votes}/{needed_votes}"
                                )
                                if votes >= needed_votes:
                                    # Become leader
                                    with self.role_lock:
                                        if self.role == ServerRole.CANDIDATE:
                                            self.role = ServerRole.LEADER
                                            with self.leader_lock:
                                                self.leader_host = self.host
                                                self.leader_port = self.port
                                            logging.info(
                                                f"Elected leader (term={current_term}) with {votes}/{alive_count} active votes."
                                            )
                                            self._send_initial_heartbeat()
                                            self.election_in_progress = False
                                            return
                except grpc.RpcError as e:
                    logging.error(f"RPC error requesting vote from {addr}: {e}")
                    replica.is_alive = False
            except Exception as e:
                logging.error(f"Failed to request vote from {addr}: {e}")
                replica.is_alive = False

        # If don't become leader
        with self.role_lock:
            if self.role == ServerRole.CANDIDATE:
                self.role = ServerRole.FOLLOWER
                logging.info(
                    f"Election failed. Returning to follower. Got {votes}/{alive_count} active votes."
                )
        self.election_in_progress = False

    def _send_initial_heartbeat(self) -> None:
        """Send an immediate heartbeat after becoming leader."""
        if self.role != ServerRole.LEADER:
            return

        for addr, replica in self.replicas.items():
            try:
                if not replica.is_alive:
                    continue
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
                channel.close()

                replica.is_alive = True
                replica.last_heartbeat = time.time()
            except Exception as e:
                logging.error(f"Failed sending initial heartbeat to {addr}: {e}")
                replica.is_alive = False

    def _send_heartbeats(self) -> None:
        """Send periodic heartbeats if leader, and update replica's is_alive status."""
        while True:
            try:
                with self.role_lock:
                    if self.role == ServerRole.LEADER:
                        # Count how many are alive (including self=1)
                        with self.replica_lock:
                            alive_count = 1
                            for rinfo in self.replicas.values():
                                if rinfo.is_alive:
                                    alive_count += 1

                        # Send heartbeat to each alive replica
                        acks = 1  # implicit self ack
                        for addr, replica in list(self.replicas.items()):
                            if not replica.is_alive:
                                continue
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
                                response = stub.HandleReplication(request, timeout=1.0)
                                channel.close()

                                replica.is_alive = True
                                replica.last_heartbeat = time.time()
                                acks += 1
                                logging.debug(f"Heartbeat success to {addr}.")
                            except grpc.RpcError:
                                replica.is_alive = False
                                logging.warning(f"Heartbeat failed to {addr}.")
                            except Exception as e:
                                replica.is_alive = False
                                logging.error(f"Error sending heartbeat to {addr}: {e}")

                        # Decide if we still keep leadership based on majority of active servers
                        needed_acks = (alive_count // 2) + 1
                        if acks < needed_acks:
                            logging.warning(
                                f"Leader sees only {acks}/{alive_count} active acks, needed={needed_acks}. Stepping down."
                            )
                            with self.role_lock:
                                if self.role == ServerRole.LEADER:
                                    self.role = ServerRole.FOLLOWER
                                    logging.info("Stepped down as leader due to losing majority of active servers.")
            except Exception as e:
                logging.error(f"Error in heartbeat loop: {e}")
            finally:
                time.sleep(self.HEARTBEAT_INTERVAL)

    def replicate_message(self, message_id: int, sender: str, recipient: str, content: str) -> bool:
        """
        Attempt to replicate a chat message to the other alive followers.
        Requires a majority of *active* nodes to acknowledge.
        """
        if self.role != ServerRole.LEADER:
            logging.error("replicate_message called on non-leader.")
            return False

        acks = 1
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

        with self.replica_lock:
            # Count how many are alive in total (leader + replicas)
            alive_count = 1  # self
            for rinfo in self.replicas.values():
                if rinfo.is_alive:
                    alive_count += 1

        # Send replication to each alive replica
        for addr, replica in self.replicas.items():
            if not replica.is_alive:
                continue
            try:
                channel = grpc.insecure_channel(f"{replica.host}:{replica.port}")
                stub = chat_pb2_grpc.ChatServerStub(channel)
                response = stub.HandleReplication(request, timeout=1.0)
                channel.close()

                if (
                    response.type == chat_pb2.ReplicationType.REPLICATION_RESPONSE
                    and response.replication_response.success
                ):
                    acks += 1
                    logging.debug(f"Message replication ack from {addr}.")
            except Exception as e:
                logging.error(f"Failed to replicate message to {addr}: {e}")
                continue

        # Majority of active servers
        needed_acks = (alive_count // 2) + 1
        success = (acks >= needed_acks)

        logging.info(
            f"[replicate_message] alive_count={alive_count}, acks={acks}, needed={needed_acks}, success={success}."
        )

        if success:
            self.last_log_index += 1
            self.last_log_term = self.term
            self.commit_index = self.last_log_index

        return success

    def replicate_account(self, username: str) -> bool:
        """
        Replicate account creation to other alive followers.
        Requires a majority of *active* nodes to acknowledge.
        """
        if self.role != ServerRole.LEADER:
            logging.error("replicate_account called on non-leader.")
            return False

        acks = 1  # self
        account_replication = chat_pb2.AccountReplication(username=username)
        request = chat_pb2.ReplicationMessage(
            type=chat_pb2.ReplicationType.REPLICATE_ACCOUNT,
            term=self.term,
            server_id=f"{self.host}:{self.port}",
            account_replication=account_replication,
            timestamp=time.time(),
        )
        logging.debug(
            f"Replicating account creation for '{username}' to followers."
        )

        with self.replica_lock:
            alive_count = 1
            for rinfo in self.replicas.values():
                if rinfo.is_alive:
                    alive_count += 1

        for addr, replica in self.replicas.items():
            if not replica.is_alive:
                continue
            try:
                channel = grpc.insecure_channel(f"{replica.host}:{replica.port}")
                stub = chat_pb2_grpc.ChatServerStub(channel)
                response = stub.HandleReplication(request, timeout=1.0)
                channel.close()
                if (
                    response.type == chat_pb2.ReplicationType.REPLICATION_RESPONSE
                    and response.replication_response.success
                ):
                    acks += 1
                    logging.debug(f"Account replication ack from {addr}.")
                else:
                    logging.error(f"Account replication from {addr} returned failure.")
            except Exception as e:
                logging.exception(f"Failed to replicate account to {addr}: {e}")
                continue

        needed_acks = (alive_count // 2) + 1
        success = (acks >= needed_acks)
        logging.info(
            f"Account '{username}' replication: acks={acks}, alive_count={alive_count}, needed={needed_acks}, success={success}."
        )
        return success

    def replicate_operation(self, replication_request: chat_pb2.ReplicationMessage) -> bool:
        """
        Generic replication for delete operations or mark-read.
        Requires majority of *active* nodes.
        """
        if self.role != ServerRole.LEADER:
            logging.error("replicate_operation called on non-leader.")
            return False

        acks = 1
        with self.replica_lock:
            alive_count = 1
            for rinfo in self.replicas.values():
                if rinfo.is_alive:
                    alive_count += 1

        for addr, replica in self.replicas.items():
            if not replica.is_alive:
                continue
            try:
                channel = grpc.insecure_channel(f"{replica.host}:{replica.port}")
                stub = chat_pb2_grpc.ChatServerStub(channel)
                response = stub.HandleReplication(replication_request, timeout=1.0)
                channel.close()
                if (
                    response.type == chat_pb2.ReplicationType.REPLICATION_RESPONSE
                    and response.replication_response.success
                ):
                    acks += 1
            except Exception as e:
                logging.error(f"Failed to replicate operation to {addr}: {e}")
                continue

        needed_acks = (alive_count // 2) + 1
        success = (acks >= needed_acks)
        logging.info(
            f"[replicate_operation] acks={acks}, alive_count={alive_count}, needed={needed_acks}, success={success}."
        )
        return success

    def handle_replication_message(
        self, message: chat_pb2.ReplicationMessage
    ) -> chat_pb2.ReplicationMessage:
        """
        Handle incoming replication messages from other servers (vote requests, heartbeats, etc.).
        """
        with self.term_lock:
            if message.term > self.term:
                self.term = message.term
                with self.role_lock:
                    self.role = ServerRole.FOLLOWER
                with self.vote_lock:
                    self.voted_for = None
                self.election_in_progress = False
                self.last_leader_contact = time.time()
            elif message.term < self.term:
                # We are ahead in terms, so reject
                return chat_pb2.ReplicationMessage(
                    type=chat_pb2.ReplicationType.REPLICATION_ERROR,
                    term=self.term,
                    server_id=f"{self.host}:{self.port}",
                    timestamp=time.time(),
                )

        if message.type == chat_pb2.ReplicationType.REQUEST_VOTE:
            # Vote request from a candidate
            with self.vote_lock:
                vote_granted = False
                if self.voted_for is None or self.voted_for == message.server_id:
                    candidate_log_ok = (
                        message.vote_request.last_log_term > self.last_log_term
                        or (
                            message.vote_request.last_log_term == self.last_log_term
                            and message.vote_request.last_log_index >= self.last_log_index
                        )
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
                # If same term, convert to follower if not follower
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
            # Follower storing a new message
            if message.term == self.term:
                self.last_leader_contact = time.time()

            msg_id = message.message_replication.message_id
            sender = message.message_replication.sender
            recipient = message.message_replication.recipient
            content = message.message_replication.content

            delivered = False
            # Check if message already exists
            existing = self.db.get_messages_between_users(sender, recipient)
            for msg in existing.get("messages", []):
                if msg.get("id") == msg_id:
                    return chat_pb2.ReplicationMessage(
                        type=chat_pb2.ReplicationType.REPLICATION_RESPONSE,
                        term=self.term,
                        server_id=f"{self.host}:{self.port}",
                        replication_response=chat_pb2.ReplicationResponse(
                            success=True, message_id=msg_id
                        ),
                        timestamp=time.time(),
                    )

            # Store new message
            stored_id = self.db.store_message(
                sender=sender,
                recipient=recipient,
                content=content,
                is_delivered=delivered,
                forced_id=msg_id,
            )
            if stored_id is not None:
                return chat_pb2.ReplicationMessage(
                    type=chat_pb2.ReplicationType.REPLICATION_RESPONSE,
                    term=self.term,
                    server_id=f"{self.host}:{self.port}",
                    replication_response=chat_pb2.ReplicationResponse(
                        success=True, message_id=msg_id
                    ),
                    timestamp=time.time(),
                )
            else:
                return chat_pb2.ReplicationMessage(
                    type=chat_pb2.ReplicationType.REPLICATION_RESPONSE,
                    term=self.term,
                    server_id=f"{self.host}:{self.port}",
                    replication_response=chat_pb2.ReplicationResponse(
                        success=False, message_id=msg_id
                    ),
                    timestamp=time.time(),
                )

        elif message.type == chat_pb2.ReplicationType.REPLICATE_ACCOUNT:
            username = message.account_replication.username
            if self.db.user_exists(username):
                success = True
            else:
                success = self.db.create_account(username, "")
            return chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATION_RESPONSE,
                term=self.term,
                server_id=f"{self.host}:{self.port}",
                replication_response=chat_pb2.ReplicationResponse(
                    success=success, message_id=0
                ),
                timestamp=time.time(),
            )

        elif message.type == chat_pb2.ReplicationType.REPLICATE_DELETE_MESSAGES:
            deletion_dict = MessageToDict(message.deletion)
            message_ids = deletion_dict.get("messageIds", [])
            username = deletion_dict.get("username", "")
            success = self.db.delete_messages(username, message_ids)
            return chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATION_RESPONSE,
                term=self.term,
                server_id=f"{self.host}:{self.port}",
                replication_response=chat_pb2.ReplicationResponse(
                    success=success, message_id=0
                ),
                timestamp=time.time(),
            )

        elif message.type == chat_pb2.ReplicationType.REPLICATE_DELETE_ACCOUNT:
            deletion_dict = MessageToDict(message.deletion)
            username = deletion_dict.get("username", "")
            success = self.db.delete_account(username)
            return chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATION_RESPONSE,
                term=self.term,
                server_id=f"{self.host}:{self.port}",
                replication_response=chat_pb2.ReplicationResponse(
                    success=success, message_id=0
                ),
                timestamp=time.time(),
            )

        elif message.type == chat_pb2.ReplicationType.REPLICATE_MARK_READ:
            deletion_dict = MessageToDict(message.deletion)
            username = deletion_dict.get("username", "")
            message_ids = deletion_dict.get("messageIds", [])
            logging.debug(f"Mark read replication for user={username}, message_ids={message_ids}")
            success = self.db.mark_messages_as_read(username, message_ids)
            return chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATION_RESPONSE,
                term=self.term,
                server_id=f"{self.host}:{self.port}",
                replication_response=chat_pb2.ReplicationResponse(
                    success=success, message_id=0
                ),
                timestamp=time.time(),
            )

        # Default unknown type
        return chat_pb2.ReplicationMessage(
            type=chat_pb2.ReplicationType.REPLICATION_ERROR,
            term=self.term,
            server_id=f"{self.host}:{self.port}",
            timestamp=time.time(),
        )
