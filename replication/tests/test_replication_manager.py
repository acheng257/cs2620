import time
import unittest
import threading
from typing import Dict, Any
from unittest.mock import patch

import grpc
from google.protobuf.json_format import ParseDict, MessageToDict
from google.protobuf.struct_pb2 import Struct

from src.replication.replication_manager import (
    ReplicationManager,
    ServerRole,
    heartbeat_logger,
    replication_logger,
    ReplicaInfo,
)
from src.protocols.grpc import chat_pb2
import src.protocols.grpc.chat_pb2_grpc as chat_pb2_grpc


# --- Helper Fake Database Manager for replication tests ---
class FakeDB:
    """A fake DB that implements only the methods used in replication."""

    def __init__(self):
        self.accounts = {}
        self.messages = {}
        self.message_counter = 1

    def create_account(self, username: str, password: str) -> bool:
        if username in self.accounts:
            return False
        self.accounts[username] = password
        return True

    def user_exists(self, username: str) -> bool:
        return username in self.accounts

    def store_message(
        self,
        sender: str,
        recipient: str,
        content: str,
        is_delivered: bool = False,
        forced_id: int = None,
    ) -> int:
        msg_id = forced_id if forced_id is not None else self.message_counter
        if forced_id is None:
            self.message_counter += 1
        self.messages[msg_id] = {
            "id": msg_id,
            "sender": sender,
            "recipient": recipient,
            "content": content,
            "is_delivered": is_delivered,
        }
        return msg_id

    def delete_messages(self, username: str, message_ids: list) -> bool:
        for mid in message_ids:
            self.messages.pop(mid, None)
        return True

    def delete_account(self, username: str) -> bool:
        if username in self.accounts:
            del self.accounts[username]
            return True
        return False

    def mark_messages_as_read(self, username: str, message_ids: list) -> bool:
        # For testing, simply return True.
        return True

    def get_messages_between_users(
        self, user1: str, user2: str, offset: int = 0, limit: int = 999999
    ) -> Dict[str, Any]:
        # Return all messages where one user is sender and the other recipient.
        conversation = [
            msg
            for msg in self.messages.values()
            if (msg["sender"] == user1 and msg["recipient"] == user2)
            or (msg["sender"] == user2 and msg["recipient"] == user1)
        ]
        # For simplicity, sort by message id.
        conversation.sort(key=lambda m: m["id"])
        total = len(conversation)
        return {"messages": conversation[offset : offset + limit], "total": total}


# --- Fake Stub and Channel for patching gRPC calls ---
class FakeStub:
    def HandleReplication(self, request, timeout=None):
        # For replicate message, return a response with the same message id.
        if request.type == chat_pb2.ReplicationType.REPLICATE_MESSAGE:
            message_id = request.message_replication.message_id
        else:
            message_id = 0
        return chat_pb2.ReplicationMessage(
            type=chat_pb2.ReplicationType.REPLICATION_RESPONSE,
            replication_response=chat_pb2.ReplicationResponse(success=True, message_id=message_id),
            term=request.term,
            server_id=request.server_id,
            timestamp=time.time(),
        )


class FakeChannel:
    def close(self):
        pass


# --- Test suite for the replication manager ---
class TestReplicationManager(unittest.TestCase):
    def setUp(self):
        self.host = "127.0.0.1"
        self.port = 50051
        self.replicas = ["127.0.0.1:50052", "127.0.0.1:50053"]
        self.fake_db = FakeDB()
        self.rm = ReplicationManager(
            host=self.host, port=self.port, replica_addresses=self.replicas, db=self.fake_db
        )
        # Disable elections and force leader role for testing.
        self.rm.election_in_progress = False
        self.rm.last_leader_contact = time.time()
        self.rm.role = ServerRole.LEADER

    def tearDown(self):
        self.rm.election_timeout.set()

    def _make_replication_msg(
        self, rep_type: int, extra: Dict[str, Any] = None
    ) -> chat_pb2.ReplicationMessage:
        """Helper to build a replication message with the given type and extra fields."""
        extra = extra or {}
        if rep_type == chat_pb2.ReplicationType.REQUEST_VOTE:
            vote_req = chat_pb2.VoteRequest(
                last_log_term=extra.get("last_log_term", self.rm.last_log_term),
                last_log_index=extra.get("last_log_index", self.rm.last_log_index),
            )
            msg = chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REQUEST_VOTE,
                term=self.rm.term + 1,
                server_id="127.0.0.1:50052",
                vote_request=vote_req,
                timestamp=time.time(),
            )
        elif rep_type == chat_pb2.ReplicationType.HEARTBEAT:
            heartbeat = chat_pb2.Heartbeat(
                commit_index=extra.get("commit_index", self.rm.commit_index)
            )
            msg = chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.HEARTBEAT,
                term=self.rm.term,
                server_id=f"{self.host}:{self.port}",
                heartbeat=heartbeat,
                timestamp=time.time(),
            )
        elif rep_type == chat_pb2.ReplicationType.REPLICATE_MESSAGE:
            msg_rep = chat_pb2.MessageReplication(
                message_id=extra.get("message_id", 1),
                sender=extra.get("sender", "user1"),
                recipient=extra.get("recipient", "user2"),
                content=extra.get("content", "Test replication"),
            )
            msg = chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATE_MESSAGE,
                term=self.rm.term,
                server_id=f"{self.host}:{self.port}",
                message_replication=msg_rep,
                timestamp=time.time(),
            )
        elif rep_type == chat_pb2.ReplicationType.REPLICATE_ACCOUNT:
            acc_rep = chat_pb2.AccountReplication(username=extra.get("username", "user1"))
            msg = chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATE_ACCOUNT,
                term=self.rm.term,
                server_id=f"{self.host}:{self.port}",
                account_replication=acc_rep,
                timestamp=time.time(),
            )
        elif rep_type == chat_pb2.ReplicationType.REPLICATE_DELETE_MESSAGES:
            deletion_payload = {
                "messageIds": extra.get("message_ids", [1, 2]),
                "username": extra.get("username", "user1"),
            }
            msg = chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATE_DELETE_MESSAGES,
                term=self.rm.term,
                server_id=f"{self.host}:{self.port}",
                deletion=ParseDict(deletion_payload, chat_pb2.DeletionPayload()),
                timestamp=time.time(),
            )
        elif rep_type == chat_pb2.ReplicationType.REPLICATE_DELETE_ACCOUNT:
            deletion_payload = {"username": extra.get("username", "user1")}
            msg = chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATE_DELETE_ACCOUNT,
                term=self.rm.term,
                server_id=f"{self.host}:{self.port}",
                deletion=ParseDict(deletion_payload, chat_pb2.DeletionPayload()),
                timestamp=time.time(),
            )
        elif rep_type == chat_pb2.ReplicationType.REPLICATE_MARK_READ:
            deletion_payload = {
                "username": extra.get("username", "user1"),
                "messageIds": extra.get("message_ids", [1]),
            }
            msg = chat_pb2.ReplicationMessage(
                type=chat_pb2.ReplicationType.REPLICATE_MARK_READ,
                term=self.rm.term,
                server_id=f"{self.host}:{self.port}",
                deletion=ParseDict(deletion_payload, chat_pb2.DeletionPayload()),
                timestamp=time.time(),
            )
        else:
            msg = chat_pb2.ReplicationMessage(
                type=999,
                term=self.rm.term,
                server_id=f"{self.host}:{self.port}",
                timestamp=time.time(),
            )
        return msg

    def test_request_vote(self):
        req = self._make_replication_msg(chat_pb2.ReplicationType.REQUEST_VOTE)
        resp = self.rm.handle_replication_message(req)
        self.assertEqual(resp.type, chat_pb2.ReplicationType.VOTE_RESPONSE)
        self.assertTrue(resp.vote_response.vote_granted)
        self.assertEqual(self.rm.term, req.term)

    def test_heartbeat(self):
        req = self._make_replication_msg(chat_pb2.ReplicationType.HEARTBEAT, {"commit_index": 5})
        self.rm.leader_host = "oldhost"
        self.rm.leader_port = 9999
        resp = self.rm.handle_replication_message(req)
        self.assertEqual(resp.type, chat_pb2.ReplicationType.REPLICATION_SUCCESS)
        self.assertEqual(self.rm.leader_host, self.host)
        self.assertEqual(self.rm.leader_port, self.port)

    def test_replicate_message(self):
        extra = {
            "message_id": 42,
            "sender": "user1",
            "recipient": "user2",
            "content": "Hello Replication",
        }
        req = self._make_replication_msg(chat_pb2.ReplicationType.REPLICATE_MESSAGE, extra)
        resp = self.rm.handle_replication_message(req)
        self.assertEqual(resp.type, chat_pb2.ReplicationType.REPLICATION_RESPONSE)
        self.assertTrue(resp.replication_response.success)
        self.assertEqual(resp.replication_response.message_id, 42)

    def test_replicate_account(self):
        extra = {"username": "user1"}
        req = self._make_replication_msg(chat_pb2.ReplicationType.REPLICATE_ACCOUNT, extra)
        resp = self.rm.handle_replication_message(req)
        self.assertEqual(resp.type, chat_pb2.ReplicationType.REPLICATION_RESPONSE)
        self.assertTrue(resp.replication_response.success)
        # Replicating the same account again should also succeed (idempotence).
        resp2 = self.rm.handle_replication_message(req)
        self.assertTrue(resp2.replication_response.success)

    def test_replicate_delete_messages(self):
        extra = {"username": "user1", "message_ids": [1, 2, 3]}
        req = self._make_replication_msg(chat_pb2.ReplicationType.REPLICATE_DELETE_MESSAGES, extra)
        resp = self.rm.handle_replication_message(req)
        self.assertEqual(resp.type, chat_pb2.ReplicationType.REPLICATION_RESPONSE)
        self.assertTrue(resp.replication_response.success)

    def test_replicate_delete_account(self):
        self.fake_db.create_account("user1", "pass")
        extra = {"username": "user1"}
        req = self._make_replication_msg(chat_pb2.ReplicationType.REPLICATE_DELETE_ACCOUNT, extra)
        resp = self.rm.handle_replication_message(req)
        self.assertEqual(resp.type, chat_pb2.ReplicationType.REPLICATION_RESPONSE)
        self.assertTrue(resp.replication_response.success)
        self.assertFalse(self.fake_db.user_exists("user1"))

    def test_replicate_mark_read(self):
        extra = {"username": "user1", "message_ids": [10, 20]}
        req = self._make_replication_msg(chat_pb2.ReplicationType.REPLICATE_MARK_READ, extra)
        resp = self.rm.handle_replication_message(req)
        self.assertEqual(resp.type, chat_pb2.ReplicationType.REPLICATION_RESPONSE)
        self.assertTrue(resp.replication_response.success)

    def test_unknown_replication_type(self):
        req = self._make_replication_msg(999)
        resp = self.rm.handle_replication_message(req)
        self.assertEqual(resp.type, chat_pb2.ReplicationType.REPLICATION_ERROR)

    @patch("src.replication.replication_manager.grpc.insecure_channel", return_value=FakeChannel())
    @patch(
        "src.replication.replication_manager.chat_pb2_grpc.ChatServerStub", return_value=FakeStub()
    )
    def test_replicate_message_success(self, fake_stub, fake_channel):
        # Test the replicate_message method when all replicas respond successfully.
        # Since our FakeStub always returns a successful replication response,
        # the leader should obtain enough acks.
        result = self.rm.replicate_message(
            message_id=100, sender="userA", recipient="userB", content="Test Message"
        )
        self.assertTrue(result)
        self.assertEqual(self.rm.commit_index, self.rm.last_log_index)

    @patch("src.replication.replication_manager.grpc.insecure_channel", return_value=FakeChannel())
    @patch(
        "src.replication.replication_manager.chat_pb2_grpc.ChatServerStub", return_value=FakeStub()
    )
    def test_replicate_account_success(self, fake_stub, fake_channel):
        # Test the replicate_account method.
        result = self.rm.replicate_account("userX")
        self.assertTrue(result)

    @patch("src.replication.replication_manager.grpc.insecure_channel", return_value=FakeChannel())
    @patch(
        "src.replication.replication_manager.chat_pb2_grpc.ChatServerStub", return_value=FakeStub()
    )
    def test_replicate_operation_success(self, fake_stub, fake_channel):
        # Build a generic replication message (for a delete operation, for example)
        deletion_payload = {"messageIds": [10, 20], "username": "userY"}
        replication_request = chat_pb2.ReplicationMessage(
            type=chat_pb2.ReplicationType.REPLICATE_DELETE_MESSAGES,
            term=self.rm.term,
            server_id=f"{self.host}:{self.port}",
            deletion=ParseDict(deletion_payload, chat_pb2.DeletionPayload()),
            timestamp=time.time(),
        )
        result = self.rm.replicate_operation(replication_request)
        self.assertTrue(result)

    def test_handle_replication_message_vote_request_decline(self):
        # Setup the local log state to be more up-to-date.
        self.rm.last_log_term = 5
        self.rm.last_log_index = 10
        # Create a vote request with an outdated candidate log.
        vote_req = chat_pb2.VoteRequest(last_log_term=4, last_log_index=9)
        req = chat_pb2.ReplicationMessage(
            type=chat_pb2.ReplicationType.REQUEST_VOTE,
            term=self.rm.term + 1,
            server_id="127.0.0.1:50052",
            vote_request=vote_req,
            timestamp=time.time(),
        )
        resp = self.rm.handle_replication_message(req)
        self.assertEqual(resp.type, chat_pb2.ReplicationType.VOTE_RESPONSE)
        self.assertFalse(resp.vote_response.vote_granted)

    def test_handle_replication_message_replicate_message_existing(self):
        # Pre-store a message in the fake DB so that a replication request for the same ID
        # will detect the message already exists.
        message_id = 55
        sender = "user1"
        recipient = "user2"
        content = "Existing message"
        self.fake_db.store_message(sender, recipient, content, forced_id=message_id)

        # Create a replication message with the same id and content.
        req = self._make_replication_msg(
            chat_pb2.ReplicationType.REPLICATE_MESSAGE,
            {
                "message_id": message_id,
                "sender": sender,
                "recipient": recipient,
                "content": content,
            },
        )
        resp = self.rm.handle_replication_message(req)
        self.assertEqual(resp.type, chat_pb2.ReplicationType.REPLICATION_RESPONSE)
        self.assertTrue(resp.replication_response.success)
        self.assertEqual(resp.replication_response.message_id, message_id)

    def test_handle_replication_message_lower_term(self):
        # Increase our current term
        self.rm.term = 10
        # Create a heartbeat message with a lower term.
        req = self._make_replication_msg(chat_pb2.ReplicationType.HEARTBEAT, {"commit_index": 5})
        req.term = 5  # Lower than our current term
        resp = self.rm.handle_replication_message(req)
        self.assertEqual(resp.type, chat_pb2.ReplicationType.REPLICATION_ERROR)
        self.assertEqual(resp.term, self.rm.term)

    def test_election_stepping_down(self):
        # Simulate a situation where a replica responds with a higher term than the candidate's term.
        original_term = self.rm.term
        test_addr = list(self.rm.replicas.keys())[0]

        # Define a stub that returns a vote response with a term higher than the candidate's.
        class FakeHighTermStub:
            def HandleReplication(self, request, timeout=None):
                return chat_pb2.ReplicationMessage(
                    type=chat_pb2.ReplicationType.VOTE_RESPONSE,
                    vote_response=chat_pb2.VoteResponse(vote_granted=True),
                    term=original_term + 5,  # simulate a higher term
                    server_id=request.server_id,
                    timestamp=time.time(),
                )

        with patch(
            "src.replication.replication_manager.grpc.insecure_channel", return_value=FakeChannel()
        ):
            with patch(
                "src.replication.replication_manager.chat_pb2_grpc.ChatServerStub",
                return_value=FakeHighTermStub(),
            ):
                self.rm._start_election()
                # After processing a higher-term vote response, the candidate should step down.
                self.assertEqual(self.rm.role, ServerRole.FOLLOWER)
                self.assertEqual(self.rm.term, original_term + 5)

    def test_replicate_message_non_leader(self):
        # When not the leader, replicate_message should return False.
        self.rm.role = ServerRole.FOLLOWER
        result = self.rm.replicate_message(
            message_id=101, sender="userA", recipient="userB", content="Test"
        )
        self.assertFalse(result)

    def test_replicate_account_non_leader(self):
        # When not the leader, replicate_account should immediately return False.
        self.rm.role = ServerRole.FOLLOWER
        result = self.rm.replicate_account("userNonLeader")
        self.assertFalse(result)

    def test_replicate_operation_non_leader(self):
        # When not the leader, replicate_operation should immediately return False.
        self.rm.role = ServerRole.FOLLOWER
        deletion_payload = {"username": "userTest", "messageIds": [100]}
        req = chat_pb2.ReplicationMessage(
            type=chat_pb2.ReplicationType.REPLICATE_MARK_READ,
            term=self.rm.term,
            server_id=f"{self.host}:{self.port}",
            deletion=ParseDict(deletion_payload, chat_pb2.DeletionPayload()),
            timestamp=time.time(),
        )
        result = self.rm.replicate_operation(req)
        self.assertFalse(result)

    def test_send_initial_heartbeat_failure(self):
        # Add a replica that will simulate a failure when sending an initial heartbeat.
        failing_addr = "127.0.0.1:50099"
        self.rm.replicas[failing_addr] = ReplicaInfo(host="127.0.0.1", port=50099, is_alive=True)

        # Patch grpc.insecure_channel so that for this replica it raises an exception.
        def fake_insecure_channel_fail(target):
            if "50099" in target:
                raise Exception("Connection failed")
            return FakeChannel()

        with patch(
            "src.replication.replication_manager.grpc.insecure_channel",
            side_effect=fake_insecure_channel_fail,
        ):
            self.rm.role = ServerRole.LEADER
            self.rm._send_initial_heartbeat()
            self.assertFalse(self.rm.replicas[failing_addr].is_alive)


if __name__ == "__main__":
    unittest.main()
