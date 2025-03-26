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
from src.replication.replication_manager import ReplicationManager, ServerRole

import logging
logging.basicConfig(level=logging.DEBUG)

class ChatServer(chat_pb2_grpc.ChatServerServicer):
    """
    gRPC server implementation for the chat service.
    Integrates with ReplicationManager for leader-follower replication.
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

        self.replication_manager = ReplicationManager(
            host=host,
            port=port,
            replica_addresses=replica_addresses or [],
            db=self.db
        )


    def CreateAccount(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
        logging.debug("role is: %s", self.replication_manager.role)
        # If not leader, forward the request to the leader.
        if self.replication_manager.role != ServerRole.LEADER:
            logging.debug("Not leader, forwarding CreateAccount request to leader")
            try:
                leader_address = f"{self.replication_manager.leader_host}:{self.replication_manager.leader_port}"
                logging.debug("Leader information: host=%s, port=%s", self.replication_manager.leader_host, self.replication_manager.leader_port)
                logging.debug("Attempting to forward CreateAccount request to leader at %s", leader_address)
                channel = grpc.insecure_channel(leader_address)
                stub = chat_pb2_grpc.ChatServerStub(channel)
                response = stub.CreateAccount(request, timeout=5.0)
                logging.debug("Received response from leader: %s", response)
                channel.close()
                return response
            except Exception as e:
                logging.error("Failed to forward CreateAccount to leader: %s", e)
                return chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.ERROR,
                    payload=ParseDict({"text": f"Failed to forward to leader: {e}"}, Struct()),
                    timestamp=time.time(),
                )

        # Leader branch: Create account locally.
        username = request.sender
        if self.db.user_exists(username):
            logging.debug("Account for '%s' already exists.", username)
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({"text": "Username already exists"}, Struct()),
                timestamp=time.time(),
            )

        logging.debug("Creating account for '%s' locally as leader.", username)
        if not self.db.create_account(username, ""):
            logging.error("Failed to create account for '%s' locally.", username)
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({"text": "Failed to create account locally"}, Struct()),
                timestamp=time.time(),
            )

        # Replicate to followers.
        logging.debug("Starting replication to followers for account creation.")
        if not self.replication_manager.replicate_account(username):
            logging.error("Failed to replicate account creation.")
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({"text": "Failed to replicate account creation"}, Struct()),
                timestamp=time.time(),
            )
        logging.debug("Finished replication to followers.")

        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict({"text": "Account created successfully"}, Struct()),
            timestamp=time.time(),
        )

    def Login(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
        logging.debug("Login request received from: %s", request.sender)
        start_time = time.time()
        username = request.sender

        # If the account does not exist, return an error response so the UI can prompt sign-up.
        if not self.db.user_exists(username):
            logging.debug("User does not exist. Returning error to prompt sign-up.")
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({
                    "text": "User does not exist. Account will be created automatically. Please set a password."
                }, Struct()),
                timestamp=time.time(),
            )

        logging.debug("DB check completed in %.6f seconds. User exists.", time.time() - start_time)
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict({"text": "Login successful"}, Struct()),
            timestamp=time.time(),
        )

    def SendMessage(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
        sender = request.sender
        recipient = request.recipient
        content = MessageToDict(request.payload).get("text", "")

        if not self.db.user_exists(recipient):
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({"text": "Recipient does not exist"}, Struct()),
                timestamp=time.time(),
            )

        if self.replication_manager.role != ServerRole.LEADER:
            try:
                channel = grpc.insecure_channel(f"{self.replication_manager.leader_host}:{self.replication_manager.leader_port}")
                stub = chat_pb2_grpc.ChatServerStub(channel)
                return stub.SendMessage(request)
            except Exception as e:
                return chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.ERROR,
                    payload=ParseDict({"text": f"Failed to forward message to leader: {str(e)}"}, Struct()),
                    timestamp=time.time(),
                )

        message_id = self.db.store_message(sender=sender, recipient=recipient, content=content, is_delivered=False)
        if message_id is None:
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({"text": "Failed to store message"}, Struct()),
                timestamp=time.time(),
            )

        if not self.replication_manager.replicate_message(message_id=message_id, sender=sender, recipient=recipient, content=content):
            self.db.delete_message(message_id)
            return chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.ERROR,
                payload=ParseDict({"text": "Failed to replicate message"}, Struct()),
                timestamp=time.time(),
            )

        with self.lock:
            if recipient in self.active_users:
                message = chat_pb2.ChatMessage(
                    type=chat_pb2.MessageType.SEND_MESSAGE,
                    sender=sender,
                    recipient=recipient,
                    payload=ParseDict({"text": content}, Struct()),
                    timestamp=time.time(),
                )
                for q in self.active_users[recipient]:
                    try:
                        q.put(message)
                        self.db.mark_message_as_delivered(message_id)
                    except Exception as e:
                        logging.error("Failed to deliver message to subscriber queue: %s", e)

        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict({"text": "Message sent successfully"}, Struct()),
            timestamp=time.time(),
        )

    def Subscribe(self, request: chat_pb2.ChatMessage, context) -> None:
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
            logging.error("Subscription error: %s", e)
        finally:
            with self.lock:
                if username in self.active_users:
                    self.active_users[username].remove(context.peer())
                    if not self.active_users[username]:
                        del self.active_users[username]

    def HandleReplication(self, request: chat_pb2.ReplicationMessage, context) -> chat_pb2.ReplicationMessage:
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

    def RequestVote(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
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

    def Heartbeat(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
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

    def ReplicateMessage(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
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
                    sender=msg["from"],
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


    def ListAccounts(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
        start_deser = time.perf_counter()
        payload = MessageToDict(request.payload)
        end_deser = time.perf_counter()
        print(f"[ListAccounts] Deserialization took {end_deser - start_deser:.6f} seconds")

        pattern = payload.get("pattern", "")
        page = int(payload.get("page", 1))
        per_page = 10
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

    def DeleteMessages(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
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

    def DeleteAccount(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
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

    def ListChatPartners(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
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

    def GetLeader(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
        if self.replication_manager.leader_host and self.replication_manager.leader_port:
            leader_address = f"{self.replication_manager.leader_host}:{self.replication_manager.leader_port}"
        else:
            leader_address = "Unknown"
        logging.debug("GetLeader called. Returning leader: %s", leader_address)
        return chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.SUCCESS,
            payload=ParseDict({"leader": leader_address}, Struct()),
            sender="SERVER",
            recipient=request.sender,
            timestamp=time.time(),
        )

    def MarkRead(self, request: chat_pb2.ChatMessage, context: grpc.ServicerContext) -> chat_pb2.ChatMessage:
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
        response_payload = {"text": "Read status updated successfully."} if success else {"text": "Failed to update read status."}
        response_type = chat_pb2.MessageType.SUCCESS if success else chat_pb2.MessageType.ERROR
        return chat_pb2.ChatMessage(
            type=response_type,
            payload=ParseDict(response_payload, Struct()),
            sender="SERVER",
            recipient=username,
            timestamp=time.time(),
        )


def serve(host: str, port: int) -> None:
    logging.info("Starting gRPC server on %s:%s...", host, port)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServerServicer_to_server(ChatServer(), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    logging.info("Server started. Waiting for termination...")
    server.wait_for_termination()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the gRPC Chat Server")
    parser.add_argument("--host", type=str, default="[::]", help="Host to bind the gRPC server on (default: [::])")
    parser.add_argument("--port", type=int, default=50051, help="Port to bind the gRPC server on (default: 50051)")
    parser.add_argument("--replicas", nargs="+", default=[], help="List of replica addresses (e.g., 127.0.0.1:50052 127.0.0.1:50053)")
    parser.add_argument("--db_path", type=str, default="chat.db", help="Path to database file")
    args = parser.parse_args()

    logging.info("Starting gRPC server on %s:%s with replicas: %s", args.host, args.port, args.replicas)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServerServicer_to_server(
        ChatServer(host=args.host, port=args.port, db_path=args.db_path, replica_addresses=args.replicas),
        server,
    )
    server.add_insecure_port(f"{args.host}:{args.port}")
    server.start()
    logging.info("Server started. Waiting for termination...")
    server.wait_for_termination()
