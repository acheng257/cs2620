import argparse
import logging
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
from src.replication.replication_manager import ReplicationManager


class ChatServer(chat_pb2_grpc.ChatServerServicer):
    """
    gRPC server implementation for the chat service.
    Integrates with ReplicationManager for leader-follower replication.

    This class implements all the RPC methods defined in the chat.proto service definition.
    It handles user authentication, message delivery, and account management operations.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 50051,
        db_path: str = "chat.db",
        replica_addresses: List[str] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.db: DatabaseManager = DatabaseManager(db_path)
        self.active_users: Dict[str, Set[chat_pb2_grpc.ChatServer_SubscribeStub]] = {}
        self.lock: threading.Lock = threading.Lock()

        # Initialize replication manager
        self.replication_manager = ReplicationManager(
            host=host, port=port, replica_addresses=replica_addresses or []
        )

    def CreateAccount(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """Create a new user account"""
        username = request.sender
        if self.db.user_exists(username):
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                content="Username already exists",
                timestamp=time.time(),
            )

        self.db.create_user(username)
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            content="Account created successfully",
            timestamp=time.time(),
        )

    def Login(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """Login a user"""
        username = request.sender
        if not self.db.user_exists(username):
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                content="User does not exist",
                timestamp=time.time(),
            )

        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS, content="Login successful", timestamp=time.time()
        )

    def SendMessage(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """Send a message to another user"""
        sender = request.sender
        recipient = request.recipient
        content = request.content

        # Check if recipient exists
        if not self.db.user_exists(recipient):
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                content="Recipient does not exist",
                timestamp=time.time(),
            )

        # If this server is not the leader, forward to leader
        if self.replication_manager.role != "leader":
            try:
                channel = grpc.insecure_channel(
                    f"{self.replication_manager.leader_host}:{self.replication_manager.leader_port}"
                )
                stub = chat_pb2_grpc.ChatServerStub(channel)
                return stub.SendMessage(request)
            except Exception as e:
                return chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.ERROR,
                    content=f"Failed to forward message to leader: {str(e)}",
                    timestamp=time.time(),
                )

        # Store message locally first
        message_id = self.db.store_message(
            sender=sender, recipient=recipient, content=content, is_delivered=False
        )

        if message_id is None:
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                content="Failed to store message",
                timestamp=time.time(),
            )

        # Replicate message to followers
        if not self.replication_manager.replicate_message(
            message_id=message_id, sender=sender, recipient=recipient, content=content
        ):
            # If replication fails, delete the message and return error
            self.db.delete_message(message_id)
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                content="Failed to replicate message",
                timestamp=time.time(),
            )

        # Deliver message to active subscribers
        with self.lock:
            if recipient in self.active_users:
                message = chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.SEND_MESSAGE,
                    sender=sender,
                    recipient=recipient,
                    content=content,
                    timestamp=time.time(),
                )

                for subscriber in self.active_users[recipient]:
                    try:
                        subscriber.on_message(message)
                        self.db.mark_message_delivered(message_id)
                    except Exception as e:
                        logging.error(f"Failed to deliver message to subscriber: {e}")
                        continue

        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            content="Message sent successfully",
            timestamp=time.time(),
        )

    def Subscribe(self, request: chat_pb2.ChatMessage, context) -> None:
        """Subscribe to receive messages"""
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
            logging.error(f"Subscription error: {e}")
        finally:
            with self.lock:
                if username in self.active_users:
                    self.active_users[username].remove(context.peer())
                    if not self.active_users[username]:
                        del self.active_users[username]

    def HandleReplication(
        self, request: chat_pb2.ReplicationMessage, context
    ) -> chat_pb2.ReplicationMessage:
        """Handle replication-related messages from other servers"""
        return self.replication_manager.handle_replication_message(request)

    def GetMessages(self, request: chat_pb2.ChatMessage, context) -> chat_pb2.ChatMessage:
        """Get all messages for a user"""
        username = request.sender
        messages = self.db.get_messages(username)

        if not messages:
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SUCCESS,
                content="No messages found",
                timestamp=time.time(),
            )

        # Format messages as a string
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
            content="\n".join(formatted_messages),
            timestamp=time.time(),
        )

    def RequestVote(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        """Handle vote requests from candidates"""
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
        """Handle heartbeat messages from the leader"""
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
        """Handle message replication requests from the leader"""
        payload = MessageToDict(request.payload)

        if self.replication_manager.handle_replicate_message(payload):
            # Store the message locally
            message_id = payload.get("message_id")
            sender = payload.get("sender")
            recipient = payload.get("recipient")
            content = payload.get("content")

            # Check if recipient is active on this replica
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
                        print(f"Failed to deliver replicated message: {e}")

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
        q: queue.Queue[chat_pb2.ChatMessage] = queue.Queue()
        with self.lock:
            self.active_users[username] = set()

        try:
            # Deliver undelivered messages.
            undelivered = self.db.get_undelivered_messages(username)
            for msg in undelivered:
                timestamp_val = msg.get("timestamp", time.time())
                try:
                    timestamp_val = float(timestamp_val)
                except (ValueError, TypeError):
                    timestamp_val = time.time()
                response_payload = {"text": msg["content"], "id": msg["id"]}
                start_ser = time.perf_counter()
                parsed_payload = ParseDict(response_payload, Struct())
                end_ser = time.perf_counter()
                print(
                    f"[ReadMessages] Serialization (undelivered) \
                        took {end_ser - start_ser:.6f} seconds"
                )

                chat_msg = chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.SEND_MESSAGE,
                    payload=parsed_payload,
                    sender=msg["from"],
                    recipient=username,
                    timestamp=timestamp_val,
                )
                yield chat_msg
                self.db.mark_message_as_delivered(msg["id"])

            # Continuously stream new messages.
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
                if username in self.active_users:
                    self.active_users[username].clear()

    def ListAccounts(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        start_deser = time.perf_counter()
        payload = MessageToDict(request.payload)
        end_deser = time.perf_counter()
        print(f"[ListAccounts] Deserialization took {end_deser - start_deser:.6f} seconds")

        pattern = payload.get("pattern", "")
        page = int(payload.get("page", 1))
        per_page = 10  # Number of accounts per page.
        result = self.db.list_accounts(pattern, page, per_page)

        start_ser = time.perf_counter()
        parsed_payload = ParseDict(result, Struct())
        end_ser = time.perf_counter()
        print(f"[ListAccounts] Serialization took {end_ser - start_ser:.6f} seconds")

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
        print(f"[DeleteMessages] Deserialization took {end_deser - start_deser:.6f} seconds")

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
        print(f"[DeleteMessages] Serialization took {end_ser - start_ser:.6f} seconds")

        response = chat_pb2.ChatMessage(
            type=msg_type,
            payload=parsed_payload,
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )
        return response

    def DeleteAccount(
        self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext
    ) -> chat_pb2.ChatMessage:
        username = request.sender
        if self.db.delete_account(username):
            response_payload = {"text": "Account deleted successfully."}
            start_ser = time.perf_counter()
            parsed_payload = ParseDict(response_payload, Struct())
            end_ser = time.perf_counter()
            print(f"[DeleteAccount] Serialization took {end_ser - start_ser:.6f} seconds")
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
        print(f"[ListChatPartners] Serialization took {end_ser - start_ser:.6f} seconds")

        response = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=parsed_payload,
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )
        return response

    def ReadConversation(self, request, context):
        # Expect payload to include 'partner', 'offset', and 'limit'
        start_deser = time.perf_counter()
        payload = MessageToDict(request.payload)
        end_deser = time.perf_counter()
        print(f"[ReadConversation] Deserialization took {end_deser - start_deser:.6f} seconds")

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
        print(f"[ReadConversation] Serialization took {end_ser - start_ser:.6f} seconds")

        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=parsed_payload,
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )


def serve(host: str, port: int) -> None:
    print(f"Starting gRPC server on {host}:{port}...")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServerServicer_to_server(ChatServer(), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the gRPC Chat Server")
    parser.add_argument(
        "--host",
        type=str,
        default="[::]",
        help="Host to bind the gRPC server on (default: [::])"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=50051,
        help="Port to bind the gRPC server on (default: 50051)"
    )
    parser.add_argument(
        "--replicas",
        nargs="+",    # one or more replica addresses
        default=[],  # default to an empty list if not provided
        help="List of replica addresses (e.g., 127.0.0.1:50052 127.0.0.1:50053)"
    )
    args = parser.parse_args()

    logging.basicConfig()
    # Create and start the server, passing the replicas list.
    print(f"Starting gRPC server on {args.host}:{args.port} with replicas: {args.replicas}")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServerServicer_to_server(
        ChatServer(host=args.host, port=args.port, db_path="chat.db", replica_addresses=args.replicas),
        server,
    )
    server.add_insecure_port(f"{args.host}:{args.port}")
    server.start()
    server.wait_for_termination()

