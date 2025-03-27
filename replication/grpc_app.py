"""
A Streamlit-based web interface for the replicated chat system.

This module provides a web interface for users to:
1. Connect to the chat server cluster
2. Create and manage accounts
3. Send and receive messages
4. View and manage chat history
5. Delete messages and accounts

The application uses the ChatClient class to handle all communication with the
server cluster, including automatic leader discovery and reconnection. The UI
is built using Streamlit and provides real-time updates for new messages.

The application maintains session state to track:
- User login status
- Server connection details
- Chat history and preferences
- UI state (selected chat partner, scroll position, etc.)

Example:
    ```bash
    # Run with default settings (connects to localhost:50051)
    streamlit run grpc_app.py

    # Run with specific cluster configuration
    streamlit run grpc_app.py -- --cluster-nodes "127.0.0.1:50051,127.0.0.1:50052"
    ```
"""

import argparse
import threading
import time
from typing import Dict, List, Optional, Tuple

import streamlit as st
from google.protobuf.json_format import MessageToDict, ParseDict
from streamlit_autorefresh import st_autorefresh

import src.protocols.grpc.chat_pb2 as chat_pb2
from src.chat_grpc_client import ChatClient
from src.database.db_manager import DatabaseManager
from google.protobuf.struct_pb2 import Struct


def get_leader(self) -> Optional[Tuple[str, int]]:
    """
    Queries the server for the current leader and returns a tuple (host, port).
    Assumes the server implements a GetLeader RPC that returns a ChatMessage with payload { "leader": "host:port" }.
    """
    try:
        empty_payload = ParseDict({}, Struct())
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.GET_LEADER,
            payload=empty_payload,
            sender="",  # not needed
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.GetLeader(request)
        leader_str = MessageToDict(response.payload).get("leader")
        if leader_str:
            host, port_str = leader_str.split(":")
            return host, int(port_str)
    except Exception as e:
        print(f"Error retrieving leader: {e}")
    return None


def get_cluster_nodes(self) -> List[Tuple[str, int]]:
    """
    Queries the server (presumably the leader) for its known cluster membership.
    Returns a list of (host, port) tuples.
    """
    try:
        empty_payload = ParseDict({}, Struct())
        request = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.GET_CLUSTER_NODES,
            payload=empty_payload,
            sender="",  # not needed
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.GetClusterNodes(request)
        node_list_str = MessageToDict(response.payload).get("nodes", [])
        node_list = []
        for node_str in node_list_str:
            host, port_str = node_str.split(":")
            node_list.append((host, int(port_str)))
        return node_list
    except Exception as e:
        print(f"Error retrieving cluster nodes: {e}")
    return []


# Attach this new method to ChatClient (monkey-patching for simplicity)
ChatClient.get_leader = get_leader
ChatClient.get_cluster_nodes = get_cluster_nodes


def init_session_state() -> None:
    """
    Initialize all necessary session state variables.

    This function ensures all required session state variables exist with proper
    default values. It handles:
    - User authentication state (logged_in, username)
    - Server connection details (host, port, cluster_nodes)
    - Chat state (selected partner, messages, etc.)
    - UI state (error messages, pending actions, etc.)
    """
    if "username" not in st.session_state:
        st.session_state.username = None
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "current_chat" not in st.session_state:
        st.session_state.current_chat = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "search_results" not in st.session_state:
        st.session_state.search_results = []
    if "lock" not in st.session_state:
        st.session_state.lock = threading.Lock()
    if "unread_map" not in st.session_state:
        st.session_state.unread_map = {}  # { partner_username: unread_count }
    if "messages_offset" not in st.session_state:
        st.session_state.messages_offset = 0
    if "messages_limit" not in st.session_state:
        st.session_state.messages_limit = 50
    if "scroll_to_bottom" not in st.session_state:
        st.session_state.scroll_to_bottom = True
    if "scroll_to_top" not in st.session_state:
        st.session_state.scroll_to_top = False
    if "clear_message_area" not in st.session_state:
        st.session_state.clear_message_area = False
    if "input_text" not in st.session_state:
        st.session_state.input_text = ""
    if "client_connected" not in st.session_state:
        st.session_state.client_connected = False
    if "server_host" not in st.session_state:
        st.session_state.server_host = "127.0.0.1"  # default
    if "server_port" not in st.session_state:
        st.session_state.server_port = 50051  # default
    if "server_connected" not in st.session_state:
        st.session_state.server_connected = False
    if "client" not in st.session_state:
        st.session_state.client = None
    if "error_message" not in st.session_state:
        st.session_state.error_message = ""
    if "fetch_chat_partners" not in st.session_state:
        st.session_state.fetch_chat_partners = False
    if "pending_deletions" not in st.session_state:
        st.session_state.pending_deletions = []
    if "displayed_messages" not in st.session_state:
        st.session_state.displayed_messages = []
    if "pending_username" not in st.session_state:
        st.session_state.pending_username = ""
    if "show_delete_form" not in st.session_state:
        st.session_state.show_delete_form = False
    if "global_message_limit" not in st.session_state:
        st.session_state.global_message_limit = 50
    if "conversations" not in st.session_state:
        st.session_state.conversations = {}
    if "input_key" not in st.session_state:
        st.session_state.input_key = "input_text_0"
    if "show_message_sent" not in st.session_state:
        st.session_state.show_message_sent = False


# def check_and_reconnect_leader(client: ChatClient) -> bool:
#     """
#     Check if the current connection is to the leader.
#     Returns True if we're connected to the leader (either already or after reconnecting),
#     False otherwise.
#     """
#     # First try current connection
#     try:
#         leader = client.get_leader()
#         if leader:
#             leader_host, leader_port = leader
#             if leader_host != client.host or leader_port != client.port:
#                 print(f"Detected leader change to {leader_host}:{leader_port}, reconnecting...")
#                 client.host = leader_host
#                 client.port = leader_port
#                 if client.connect():
#                     print("Successfully reconnected to new leader")
#                     if client.read_thread:
#                         client.read_thread = None
#                     client.start_read_thread()
#                     return True
#             else:
#                 return True  # Already connected to leader
#     except Exception as e:
#         print(f"Current connection failed: {e}")

#     # If current connection failed, try all known cluster nodes
#     print("Trying all known cluster nodes to find leader...")
#     for node_host, node_port in client.cluster_nodes:
#         if (node_host, node_port) == (
#             client.host,
#             client.port,
#         ):  # Skip current node as we know it failed
#             continue
#         try:
#             print(f"Trying node at {node_host}:{node_port}...")
#             temp_client = ChatClient(
#                 username="", host=node_host, port=node_port, cluster_nodes=client.cluster_nodes
#             )
#             if temp_client.connect(timeout=1):  # Short timeout for discovery
#                 leader = temp_client.get_leader()
#                 temp_client.close()
#                 if leader:
#                     leader_host, leader_port = leader
#                     print(
#                         f"Found leader through node {node_host}:{node_port}: {leader_host}:{leader_port}"
#                     )
#                     # Update client connection
#                     client.host = leader_host
#                     client.port = leader_port
#                     if client.connect():
#                         print("Successfully connected to leader")
#                         if client.read_thread:
#                             client.read_thread = None
#                         client.start_read_thread()
#                         return True
#         except Exception as e:
#             print(f"Failed to check node at {node_host}:{node_port}: {e}")
#             continue


#     print("Could not find leader through any known nodes")
#     return False
def check_and_reconnect_leader(client: ChatClient) -> bool:
    """
    Check if the current connection is to the leader.
    Returns True if we're connected to the leader (either already or after reconnecting),
    False otherwise.

    If we detect a new leader (host/port differs from what we were using),
    we clear local chat state so we can reload messages from scratch.
    """

    old_host, old_port = client.host, client.port  # remember the current host/port

    # 1. First try the current node
    try:
        leader = client.get_leader()
        if leader:
            leader_host, leader_port = leader

            # If we're already connected to that leader, just refresh cluster membership
            if (leader_host == client.host) and (leader_port == client.port):
                try:
                    updated_nodes = client.get_cluster_nodes()
                    if updated_nodes:
                        client.cluster_nodes = updated_nodes
                        print(f"Refreshed cluster nodes: {client.cluster_nodes}")
                except Exception as e:
                    print(f"Warning: Could not refresh cluster nodes from leader: {e}")
                return True
            else:
                # We are connected to a follower. Reconnect to the real leader
                print(f"Detected leader change to {leader_host}:{leader_port}, reconnecting...")
                client.host = leader_host
                client.port = leader_port
                if client.connect():
                    print("Successfully reconnected to new leader.")
                    # Start read thread
                    if client.read_thread:
                        client.read_thread = None
                    client.start_read_thread()

                    # --- CLEAR SESSION STATE IF CHANGED LEADERS ---
                    if (leader_host != old_host) or (leader_port != old_port):
                        _clear_local_chat_state()

                    # Now fetch updated cluster membership
                    try:
                        updated_nodes = client.get_cluster_nodes()
                        if updated_nodes:
                            client.cluster_nodes = updated_nodes
                            print(f"Refreshed cluster nodes: {client.cluster_nodes}")
                    except Exception as e:
                        print(f"Warning: Could not refresh cluster nodes from new leader: {e}")
                    return True
    except Exception as e:
        print(f"Current connection failed: {e}")
        # Remove the current node from the list so we don't keep retrying it
        if (client.host, client.port) in client.cluster_nodes:
            client.cluster_nodes.remove((client.host, client.port))

    # 2. If current node fails, try each known cluster node in turn
    print("Trying all known cluster nodes to find leader...")
    cluster_copy = list(client.cluster_nodes)
    for node_host, node_port in cluster_copy:
        try:
            # Skip if it's the one we just tried
            if node_host == client.host and node_port == client.port:
                continue
            print(f"Trying node at {node_host}:{node_port}...")
            temp_client = ChatClient(
                username="", host=node_host, port=node_port, cluster_nodes=client.cluster_nodes
            )
            if temp_client.connect(timeout=1):
                # If we got a connection, ask this node for the leader
                leader = temp_client.get_leader()
                temp_client.close()
                if leader:
                    leader_host, leader_port = leader
                    print(
                        f"Found leader through node {node_host}:{node_port}: {leader_host}:{leader_port}"
                    )
                    # Connect directly to the discovered leader
                    client.host = leader_host
                    client.port = leader_port
                    if client.connect():
                        print("Successfully connected to leader.")
                        if client.read_thread:
                            client.read_thread = None
                        client.start_read_thread()

                        # --- CLEAR SESSION STATE IF CHANGED LEADERS ---
                        if (leader_host != old_host) or (leader_port != old_port):
                            _clear_local_chat_state()

                        # Now fetch updated cluster membership
                        try:
                            updated_nodes = client.get_cluster_nodes()
                            if updated_nodes:
                                client.cluster_nodes = updated_nodes
                                print(f"Refreshed cluster nodes: {client.cluster_nodes}")
                        except Exception as e:
                            print(f"Warning: Could not refresh cluster nodes from new leader: {e}")
                        return True
                    else:
                        # If we fail to connect to the actual leader, remove it
                        print(
                            f"Could not connect to the actual leader at {leader_host}:{leader_port}."
                        )
                        if (leader_host, leader_port) in client.cluster_nodes:
                            client.cluster_nodes.remove((leader_host, leader_port))
                else:
                    # The node responded but didn't give us a valid leader => remove it
                    print(
                        f"Node {node_host}:{node_port} responded but gave no leader, removing it."
                    )
                    if (node_host, node_port) in client.cluster_nodes:
                        client.cluster_nodes.remove((node_host, node_port))
            else:
                # If connect() failed, remove that node
                print(f"Failed to connect to {node_host}:{node_port}, removing it.")
                if (node_host, node_port) in client.cluster_nodes:
                    client.cluster_nodes.remove((node_host, node_port))
        except Exception as e:
            print(f"Failed to check node at {node_host}:{node_port}: {e}")
            if (node_host, node_port) in client.cluster_nodes:
                client.cluster_nodes.remove((node_host, node_port))
            continue

    print("Could not find leader through any known nodes.")
    return False


def _clear_local_chat_state():
    """
    Clears out the local Streamlit session state for conversations, messages, etc.
    so we reload everything from the new leader from scratch.
    """
    # You can adjust exactly which fields you want to clear.
    # Typically we clear messages, displayed_messages, current_chat, and conversation caches.
    print("Clearing local chat state due to leader change...")
    st.session_state.messages = []
    st.session_state.displayed_messages = []
    st.session_state.conversations = {}
    st.session_state.current_chat = None
    st.session_state.unread_map = {}
    st.session_state.messages_offset = 0
    st.session_state.messages_limit = 50
    st.session_state.scroll_to_bottom = True
    st.session_state.scroll_to_top = False


def get_chat_client() -> Optional[ChatClient]:
    """
    Get the chat client from the session state, ensuring it's connected.

    The client's built-in leader check thread handles reconnection automatically,
    so this function only needs to verify the client exists and is logged in.

    Returns:
        Optional[ChatClient]: The connected chat client if available and logged in,
            None otherwise.
    """
    if (
        st.session_state.logged_in
        and st.session_state.client_connected
        and st.session_state.client is not None
    ):
        client = st.session_state.client
        if check_and_reconnect_leader(client):
            return client
        else:
            st.error("Lost connection to leader. Attempting to reconnect...")
            st.session_state.client_connected = False
    print("Chat client is not initialized or not connected to leader.")
    return None


def render_login_page() -> None:
    """
    Render the login/signup page with server connection settings.

    This function:
    1. Displays server connection settings (host, port, cluster nodes)
    2. Handles server connection attempts
    3. Manages username input
    4. Handles account creation and login
    5. Starts necessary background threads upon successful login
    """
    # If the user is already logged in, don't render the login page.
    if st.session_state.logged_in:
        return

    st.title("Secure Chat - Login / Sign Up")

    if st.session_state.error_message:
        st.error(st.session_state.error_message)

    with st.expander("Server Settings", expanded=True):
        if st.session_state.server_connected:
            st.markdown("✅ Connected to server:")
            st.code(f"{st.session_state.server_host}:{st.session_state.server_port}")
        else:
            server_host = st.text_input(
                "Server Host",
                value=st.session_state.server_host,
                key="server_host_input",
                help="Enter the server's IP address (default: 127.0.0.1)",
            )
            server_port = st.number_input(
                "Server Port",
                min_value=1,
                max_value=65535,
                value=st.session_state.server_port,
                key="server_port_input",
                help="Enter the server's port number (default: 50051)",
            )
            cluster_nodes_str = st.text_input(
                "Cluster Nodes",
                value=",".join(f"{h}:{p}" for h, p in st.session_state.cluster_nodes),
                key="cluster_nodes_input",
                help="Comma-separated list of host:port pairs for cluster nodes (e.g., 127.0.0.1:50051,127.0.0.1:50052)",
            )
            if st.button("Connect to Server"):
                if not server_host:
                    st.warning("Please enter the server's IP address.")
                else:
                    # Parse cluster nodes
                    try:
                        cluster_nodes = []
                        for node in cluster_nodes_str.split(","):
                            host, port = node.strip().split(":")
                            cluster_nodes.append((host, int(port)))
                        st.session_state.cluster_nodes = cluster_nodes
                    except Exception as e:
                        st.error(f"Invalid cluster nodes format: {e}")
                        return

                    st.session_state.server_host = server_host
                    st.session_state.server_port = int(server_port)
                    temp_client = ChatClient(
                        username="",
                        host=st.session_state.server_host,
                        port=st.session_state.server_port,
                        cluster_nodes=st.session_state.cluster_nodes,
                    )
                    if temp_client.connect():
                        if check_and_reconnect_leader(temp_client):
                            st.session_state.server_connected = True
                            st.session_state.error_message = ""
                            st.success(
                                f"Connected to leader server at {temp_client.host}:{temp_client.port}"
                            )
                            st.rerun()  # Re-run the app to use leader's address
                        else:
                            st.session_state.error_message = "Could not determine leader server."
                            st.error(st.session_state.error_message)
                        temp_client.close()
                    else:
                        st.session_state.server_connected = False
                        st.session_state.error_message = (
                            "Failed to connect to server at "
                            f"{st.session_state.server_host}:{st.session_state.server_port}"
                        )
                        st.error(st.session_state.error_message)
                        temp_client.close()

    st.markdown("---")

    if not st.session_state.server_connected:
        st.warning("Please connect to the server before logging in or creating an account.")
        return
    else:
        st.success("Successfully connected to server.")

    def on_username_submit():
        """Callback for username input"""
        username = st.session_state.username_input
        if username.strip():
            st.session_state.pending_username = username.strip()

    def on_login_submit():
        """Callback for login form"""
        password = st.session_state.login_password
        username = st.session_state.pending_username
        client = ChatClient(
            username=username,
            host=st.session_state.server_host,
            port=st.session_state.server_port,
            cluster_nodes=st.session_state.cluster_nodes,
        )
        if client.connect():
            success, error = client.login_sync(password)
            if success:
                st.session_state.username = username
                st.session_state.logged_in = True
                st.session_state.client = client
                st.session_state.client_connected = True
                st.session_state.global_message_limit = 50
                client.start_read_thread()
                client.start_leader_check_thread()
            else:
                if error and (
                    "does not exist" in error.lower()
                    or "will be created automatically" in error.lower()
                ):
                    created = client.create_account_sync(password)
                    if created:
                        st.session_state.username = username
                        st.session_state.logged_in = True
                        st.session_state.client = client
                        st.session_state.client_connected = True
                        st.session_state.global_message_limit = 50
                        client.start_read_thread()
                        client.start_leader_check_thread()
                        st.session_state.pending_username = ""
                    else:
                        st.error("Failed to create account.")
                else:
                    st.error(f"Login failed: {error}")
        else:
            st.error("Failed to connect to the server.")

    # If no pending username is set, prompt for one
    if not st.session_state.pending_username:
        username = st.text_input("Enter your unique username", key="username_input")
        st.button("Submit", on_click=on_username_submit)
        return

    username = st.session_state.pending_username

    # Check account existence using a dummy password attempt
    account_exists = False
    try:
        temp_client = ChatClient(
            username=username,
            host=st.session_state.server_host,
            port=st.session_state.server_port,
        )
        if temp_client.connect():
            success, error = temp_client.login_sync("dummy_password")
            if (
                not success
                and error
                and (
                    "does not exist" in error.lower()
                    or "will be created automatically" in error.lower()
                )
            ):
                account_exists = False
            else:
                account_exists = True
        temp_client.close()
    except Exception as e:
        st.error(f"Error checking account existence: {e}")

    if account_exists:
        st.info("Account found. Please log in by entering your password.")
        password = st.text_input("Password", type="password", key="login_password")
        st.button("Login", on_click=on_login_submit)
    else:
        st.info("No account found. Please create an account by choosing a password.")
        col1, col2 = st.columns(2)
        with col1:
            password1 = st.text_input("Enter Password", type="password", key="signup_password1")
        with col2:
            password2 = st.text_input("Confirm Password", type="password", key="signup_password2")

        if st.button("Create Account"):
            if password1 != password2:
                st.error("Passwords do not match.")
            elif len(password1) < 6:
                st.error("Password must be at least 6 characters long.")
            else:
                client = ChatClient(
                    username=username,
                    host=st.session_state.server_host,
                    port=st.session_state.server_port,
                    cluster_nodes=st.session_state.cluster_nodes,
                )
                if client.connect():
                    success = client.create_account_sync(password1)
                    if success:
                        st.session_state.username = username
                        st.session_state.logged_in = True
                        st.session_state.client = client
                        st.session_state.client_connected = True
                        st.session_state.global_message_limit = 50
                        client.start_read_thread()
                        client.start_leader_check_thread()
                        st.session_state.pending_username = ""
                    else:
                        st.error("Account creation failed. Username may already exist.")
                else:
                    st.error("Connection to server failed.")

    if st.button("Change Username"):
        st.session_state.pending_username = ""
        st.rerun()


def fetch_accounts(pattern: str = "", page: int = 1) -> None:
    client = get_chat_client()
    if client:
        try:
            response = client.list_accounts_sync(pattern, page)
            result = MessageToDict(response.payload)
            st.session_state.search_results = result.get("users", [])
        except Exception as e:
            st.warning(f"An error occurred while fetching accounts: {e}")
    else:
        st.warning("Client is not connected.")


def fetch_chat_partners() -> Tuple[List[str], Dict[str, int]]:
    client = get_chat_client()
    if client:
        response = client.list_chat_partners_sync()
        result = MessageToDict(response.payload)
        partners = result.get("chat_partners", [])
        unread_map = result.get("unread_map", {})
        st.session_state.chat_partners = partners
        st.session_state.unread_map = unread_map
        return partners, unread_map
    return [], {}


def load_conversation(partner: str, offset: int = 0, limit: int = 50) -> None:
    """
    Load messages from a conversation with a chat partner.

    This function:
    1. Retrieves messages from the server
    2. Updates the session state with the loaded messages
    3. Marks unread messages as read
    4. Updates the UI scroll position

    Args:
        partner (str): Username of the chat partner
        offset (int, optional): Number of messages to skip. Defaults to 0
        limit (int, optional): Maximum number of messages to load. Defaults to 50
    """
    client = get_chat_client()
    if client:
        max_retries = 3
        retry_delay = 1.0  # seconds

        for attempt in range(max_retries):
            try:
                # Try to reconnect to leader if needed
                if not check_and_reconnect_leader(client):
                    if attempt < max_retries - 1:
                        print(f"Failed to find leader (attempt {attempt + 1}/{max_retries})")
                        print("Waiting for leader election and retrying...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        st.error("Could not find leader after multiple attempts")
                        return

                # Try to read conversation
                response = client.read_conversation_sync(partner, offset, limit)
                result = MessageToDict(response.payload)
                db_msgs = result.get("messages", [])
                db_msgs_sorted = sorted(db_msgs, key=lambda x: x["timestamp"])
                new_messages = []
                unread_ids = []
                for m in db_msgs_sorted:
                    msg_id = int(m["id"])
                    msg = {
                        "sender": m["from"],
                        "text": m["content"],
                        "timestamp": m["timestamp"],
                        "is_read": m.get("is_read", False),
                        "is_delivered": m.get("is_delivered", True),
                        "id": msg_id,
                    }
                    if msg["sender"].strip().lower() != st.session_state.username:
                        msg["is_read"] = True
                        unread_ids.append(msg_id)
                    new_messages.append(msg)

                with st.session_state.lock:
                    st.session_state.messages = new_messages
                    st.session_state.displayed_messages = new_messages
                    st.session_state.messages_offset = offset
                    st.session_state.messages_limit = limit
                    st.session_state.scroll_to_bottom = False
                    st.session_state.scroll_to_top = True
                    st.session_state.unread_map[partner] = 0

                # Mark messages as read
                if unread_ids:
                    try:
                        mark_request = chat_pb2.ChatMessage(
                            type=chat_pb2.MessageType.MARK_READ,
                            payload=ParseDict({"message_ids": unread_ids}, Struct()),
                            sender=st.session_state.username,
                            recipient="SERVER",
                            timestamp=time.time(),
                        )
                        mark_response = client.stub.MarkRead(mark_request)
                        mark_result = MessageToDict(mark_response.payload)
                        if "success" not in mark_result.get("text", "").lower():
                            st.warning("Failed to update read status on server.")
                    except Exception as e:
                        st.warning(f"Failed to mark messages as read: {e}")

                st.write(f"Loaded {len(new_messages)} messages.")
                return  # Success, exit the retry loop

            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"Failed to load conversation (attempt {attempt + 1}/{max_retries}): {e}")
                    print("Retrying...")
                    time.sleep(retry_delay)
                    continue
                else:
                    st.error(f"Failed to load conversation: {e}")
                    return

        st.error("Failed to load conversation after multiple retries. Please try again later.")
    else:
        st.warning("Client is not connected.")


def process_incoming_realtime_messages() -> None:
    """
    Process new messages from the incoming messages queue.

    This function runs periodically to:
    1. Check for new messages in the client's incoming queue
    2. Update the UI with new messages
    3. Handle message delivery status
    4. Update unread message counts

    The function only triggers a UI rerun if there are actual changes
    (new messages or new chat partners).
    """
    client = get_chat_client()
    if client:
        changes_detected = False
        while not client.incoming_messages_queue.empty():
            msg = client.incoming_messages_queue.get()
            if msg.type == chat_pb2.MessageType.SEND_MESSAGE:
                sender = msg.sender
                text = MessageToDict(msg.payload).get("text", "")
                timestamp = msg.timestamp
                new_message = {
                    "sender": sender,
                    "text": text,
                    "timestamp": timestamp,
                    "is_read": True,
                    "is_delivered": True,
                    "id": MessageToDict(msg.payload).get("id"),
                }
                with st.session_state.lock:
                    if st.session_state.current_chat == sender:
                        # Only update messages if we're in the chat with the sender
                        st.session_state.messages.append(new_message)
                        st.session_state.messages = deduplicate_messages(st.session_state.messages)
                        if (
                            "conversations" in st.session_state
                            and st.session_state.current_chat in st.session_state.conversations
                        ):
                            conv = st.session_state.conversations[st.session_state.current_chat]
                            conv["displayed_messages"].append(new_message)
                            # TODO: shouldn't need that
                            conv["displayed_messages"] = deduplicate_messages(
                                conv["displayed_messages"]
                            )
                            if len(conv["displayed_messages"]) > conv["limit"]:
                                conv["displayed_messages"] = conv["displayed_messages"][
                                    -conv["limit"] :
                                ]
                        changes_detected = True
                        st.session_state.scroll_to_bottom = True
                    else:
                        # Update unread count and chat partners list
                        st.session_state.unread_map[sender] = (
                            st.session_state.unread_map.get(sender, 0) + 1
                        )
                        if "chat_partners" not in st.session_state:
                            st.session_state.chat_partners = []
                        if sender not in st.session_state.chat_partners:
                            st.session_state.chat_partners.append(sender)
                            changes_detected = True

                # Show notification for new message
                st.toast(f"New message from {sender}: {text}")

        # Only rerun if we detected changes that affect the UI
        if changes_detected:
            st.rerun()


def on_message_send(partner: str, new_msg: str, conv) -> None:
    """
    Handle message sending and update UI state.

    Args:
        partner: The recipient of the message
        new_msg: The message text
        conv: The current conversation state
    """
    client = get_chat_client()
    if client:
        try:
            response = client.send_message_sync(partner, new_msg)
            if "success" in MessageToDict(response.payload).get("text", "").lower():
                # Set flag to show success message after rerun
                st.session_state.show_message_sent = True
                # Generate a new key for the text input to clear it
                st.session_state.input_key = f"input_text_{int(time.time())}"
                # Load the conversation to update the display
                load_conversation(partner, 0, conv["limit"])
                conv["offset"] = 0
                conv["displayed_messages"] = st.session_state.displayed_messages.copy()
                conv["displayed_messages"] = deduplicate_messages(conv["displayed_messages"])
                st.rerun()
            else:
                st.error("Failed to send message.")
        except Exception as e:
            st.error(f"An error occurred while sending the message: {e}")
    else:
        st.error("Client is not connected.")


def render_sidebar() -> None:
    """
    Render the application sidebar with user controls and chat partner list.

    The sidebar includes:
    1. User account information and logout button
    2. Account deletion option
    3. List of chat partners with unread message counts
    4. Search functionality for finding users
    """
    st.sidebar.title("Menu")
    st.sidebar.subheader(f"Logged in as: {st.session_state.username}")

    if st.sidebar.button("Refresh Chats"):
        st.session_state.chat_partners = []
        st.session_state.unread_map = {}

    chat_partners, unread_map = fetch_chat_partners()

    with st.sidebar.expander("Existing Chats", expanded=True):
        if chat_partners:
            for partner in chat_partners:
                if partner != st.session_state.username:
                    unread_count = st.session_state.unread_map.get(partner, 0)
                    label = f"{partner}"
                    if unread_count > 0:
                        label += f" ({unread_count} unread)"
                    if st.button(label, key=f"chat_partner_{partner}"):
                        st.session_state.current_chat = partner
                        st.session_state.messages_offset = 0
                        load_conversation(partner, 0, st.session_state.global_message_limit)
                        st.session_state.scroll_to_bottom = True
                        st.session_state.scroll_to_top = False
                        st.rerun()
        else:
            st.write("No existing chats found.")

    with st.sidebar.expander("Find New Users", expanded=False):
        pattern = st.text_input("Search by username", key="search_pattern")
        if st.button("Search", key="search_button"):
            fetch_accounts(pattern, 1)
        if st.session_state.search_results:
            st.write("**Search Results:**")
            for user in st.session_state.search_results:
                if user != st.session_state.username:
                    if st.button(user, key=f"user_{user}"):
                        st.session_state.current_chat = user
                        st.session_state.messages_offset = 0
                        load_conversation(user, 0, st.session_state.global_message_limit)
                        st.session_state.scroll_to_bottom = True
                        st.session_state.scroll_to_top = False

    with st.sidebar.expander("Account Options", expanded=False):
        st.write("---")
        if st.button("Refresh Chat Partners"):
            st.session_state.fetch_chat_partners = True
            st.rerun()

        if st.button("Delete Account"):
            st.session_state.show_delete_form = True

        if st.session_state.get("show_delete_form", False):
            with st.form("delete_account_form"):
                confirm = st.checkbox(
                    "Are you sure you want to delete your account?", key="confirm_delete"
                )
                submitted = st.form_submit_button("Confirm Deletion")
                if submitted:
                    if confirm:
                        client = get_chat_client()
                        if client:
                            try:
                                response = client.delete_account_sync()
                                if (
                                    MessageToDict(response.payload)
                                    .get("text", "")
                                    .lower()
                                    .find("success")
                                    != -1
                                ):
                                    st.session_state.logged_in = False
                                    st.session_state.username = None
                                    st.session_state.current_chat = None
                                    st.session_state.messages = []
                                    st.session_state.unread_map = {}
                                    st.session_state.chat_partners = []
                                    st.session_state.search_results = []
                                    st.session_state.client = None
                                    st.session_state.client_connected = False
                                    st.session_state.server_connected = False
                                    st.session_state.error_message = ""
                                    st.session_state.pending_username = ""
                                    st.session_state.pending_deletions = []
                                    st.session_state.displayed_messages = []
                                    st.success("Account deleted successfully.")
                                    st.session_state.show_delete_form = False
                                    st.rerun()
                                else:
                                    st.error("Failed to delete account.")
                            except Exception as e:
                                st.error(f"An error occurred while deleting the account: {e}")
                        else:
                            st.error("Client is not connected.")
                    else:
                        st.warning("Please confirm the deletion.")


def deduplicate_messages(messages):
    """
    Return a new list of messages with duplicates removed.
    A 'duplicate' is defined by having the same (sender, text, timestamp).
    """
    seen = set()
    unique = []
    for msg in messages:
        # Build a key that identifies the message logically
        # If your 'id' is globally unique across servers, you could just use (msg["id"]).
        # Otherwise, use (sender, text, timestamp).
        # Round the timestamp slightly to avoid floating-point differences if desired.
        sender = msg.get("sender")
        text = msg.get("text")
        ts = float(msg.get("timestamp", 0.0))

        key = (sender, text, round(ts, 3))

        if key not in seen:
            seen.add(key)
            unique.append(msg)
    return unique


def render_chat_page_with_deletion() -> None:
    """
    Render the main chat interface with message deletion capability.

    This page shows:
    1. The current chat conversation
    2. Message input and send controls
    3. Message deletion checkboxes and confirmation
    4. Load more messages button
    5. Conversation settings (message limit)
    """
    st.title("Secure Chat")

    if st.session_state.current_chat:
        partner = st.session_state.current_chat
        st.subheader(f"Chat with {partner}")

        # Add auto-refresh for messages section only
        refresh_interval = 1  # refresh every 2 seconds
        st_autorefresh(interval=refresh_interval * 1000, key="message_refresh")

        if "conversations" not in st.session_state:
            st.session_state.conversations = {}

        if partner not in st.session_state.conversations:
            db_manager = DatabaseManager()
            conv_limit = db_manager.get_chat_message_limit(st.session_state.username, partner)
            st.session_state.conversations[partner] = {
                "displayed_messages": [],
                "offset": 0,
                "limit": conv_limit,
            }
        conv = st.session_state.conversations[partner]

        # Process any new messages before displaying
        process_incoming_realtime_messages()

        if not conv["displayed_messages"]:
            load_conversation(partner, conv["offset"], conv["limit"])
            conv["displayed_messages"] = st.session_state.displayed_messages.copy()
            conv["displayed_messages"] = deduplicate_messages(conv["displayed_messages"])

        new_limit = st.number_input(
            "Number of recent messages to display",
            min_value=5,
            max_value=1000,
            value=conv["limit"],
            step=5,
            key=f"messages_limit_input_{partner}",
        )
        if new_limit != conv["limit"]:
            conv["limit"] = new_limit
            conv["offset"] = 0
            load_conversation(partner, 0, new_limit)
            conv["displayed_messages"] = st.session_state.displayed_messages.copy()
            conv["displayed_messages"] = deduplicate_messages(conv["displayed_messages"])
            st.session_state.scroll_to_bottom = True
            st.session_state.scroll_to_top = False
            db_manager = DatabaseManager()
            db_manager.update_chat_message_limit(st.session_state.username, partner, new_limit)

        messages = conv["displayed_messages"]

        with st.container():
            with st.form("select_messages_form"):
                selected_message_ids = []
                for msg in messages:
                    print(msg)
                    sender = msg.get("sender")
                    text = msg.get("text")
                    ts = msg.get("timestamp")
                    msg_id = msg.get("id")
                    if isinstance(ts, str):
                        formatted_timestamp = ts
                    else:
                        try:
                            ts_float = float(ts)
                            formatted_timestamp = time.strftime(
                                "%Y-%m-%d %H:%M:%S", time.localtime(ts_float)
                            )
                        except Exception:
                            formatted_timestamp = "Unknown Time"

                    sender_name = "You" if sender == st.session_state.username else sender
                    cols = st.columns([4, 1])
                    with cols[0]:
                        st.markdown(f"**{sender_name}** [{formatted_timestamp}]:")
                        st.markdown(f"```\n{text}\n```")
                    with cols[1]:
                        delete_checkbox = st.checkbox(
                            "🗑️",
                            key=f"delete_{msg_id}",
                            help="Select to delete this message.",
                            label_visibility="collapsed",
                        )
                        if delete_checkbox:
                            selected_message_ids.append(msg_id)
                submit_button = st.form_submit_button(label="Delete Selected Messages")
                if submit_button:
                    if selected_message_ids:
                        st.session_state.pending_deletions = selected_message_ids
                    else:
                        st.warning("No messages selected for deletion.")

        if st.session_state.pending_deletions:
            st.markdown("### Confirm Deletion")
            with st.form("confirm_deletion_form"):
                confirm = st.checkbox(
                    "Are you sure you want to delete the selected messages?", key="confirm_deletion"
                )
                confirm_button = st.form_submit_button("Confirm Deletion")
                cancel_button = st.form_submit_button("Cancel")
                if confirm_button:
                    if confirm:
                        client = get_chat_client()
                        if client:
                            try:
                                response = client.delete_messages_sync(
                                    st.session_state.pending_deletions
                                )
                                if (
                                    MessageToDict(response.payload)
                                    .get("text", "")
                                    .lower()
                                    .find("success")
                                    != -1
                                ):
                                    st.success("Selected messages have been deleted.")
                                    load_conversation(partner, 0, conv["limit"])
                                    conv["offset"] = 0
                                    conv["displayed_messages"] = (
                                        st.session_state.displayed_messages.copy()
                                    )
                                    conv["displayed_messages"] = deduplicate_messages(
                                        conv["displayed_messages"]
                                    )
                                else:
                                    st.error("Failed to delete selected messages.")
                            except Exception as e:
                                st.error(f"An error occurred while deleting messages: {e}")
                        else:
                            st.error("Client is not connected.")
                        st.session_state.pending_deletions = []
                    else:
                        st.warning("Please confirm the deletion.")
                if cancel_button:
                    st.warning("Deletion canceled.")
                    st.session_state.pending_deletions = []

        # Show an extra container for the chat area so we can scroll it
        chat_html = """
        <div style="height:50px; padding:0.5rem;" id="chat-container">
        """
        if messages:
            chat_html += (
                "<p><em>Use the checkboxes on the right to select messages for deletion.</em></p>"
            )
        else:
            chat_html += "<p><em>No messages to display.</em></p>"
        chat_html += "</div>"

        if st.session_state.get("scroll_to_top", False):
            scroll_js = """
            <script>
                setTimeout(function(){
                    var objDiv = document.getElementById("chat-container");
                    objDiv.scrollTop = 0;
                }, 0);
            </script>
            """
            st.components.v1.html(scroll_js, height=0)
        elif st.session_state.get("scroll_to_bottom", False):
            scroll_js = """
            <script>
                setTimeout(function(){
                    var objDiv = document.getElementById("chat-container");
                    objDiv.scrollTop = objDiv.scrollHeight;
                }, 0);
            </script>
            """
            st.components.v1.html(scroll_js, height=0)

        st.markdown(chat_html, unsafe_allow_html=True)

        if st.button("Load More Messages"):
            new_offset = conv["offset"] + conv["limit"]
            load_conversation(partner, new_offset, conv["limit"])
            conv["offset"] = new_offset
            conv["displayed_messages"] = st.session_state.displayed_messages.copy()
            conv["displayed_messages"] = deduplicate_messages(conv["displayed_messages"])
            st.session_state.scroll_to_top = True
            st.session_state.scroll_to_bottom = False

        # Message input area with dynamic key
        new_msg = st.text_area(
            "Type your message",
            key=st.session_state.input_key,
            height=100,
        )
        print("new_msg", new_msg)

        # Send button with Enter key handling
        if st.button("Send") or (new_msg and new_msg.strip() and "\n" in new_msg):
            print("new_msg 2", new_msg)
            if new_msg.strip() == "":
                st.warning("Cannot send an empty message.")
            else:
                on_message_send(partner, new_msg.strip(), conv)
                # Show success message if flag is set
        if st.session_state.get("show_message_sent", False):
            st.success("Message sent.")
            st.session_state.show_message_sent = False  # Reset the flag

    else:
        st.info("Select a user from the sidebar or search to begin chat.")


def main() -> None:
    """
    Main entry point for the Streamlit application.

    This function:
    1. Parses command line arguments for server configuration
    2. Sets up the Streamlit page configuration
    3. Initializes session state
    4. Handles automatic server connection from command line args
    5. Renders either the login page or chat interface based on login state
    6. Manages background message processing
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="", help="Server host address")
    parser.add_argument("--port", type=int, default=0, help="Server port number")
    parser.add_argument(
        "--cluster-nodes",
        type=str,
        help="Comma-separated list of host:port pairs for cluster nodes",
        default="127.0.0.1:50051",
    )
    args, unknown = parser.parse_known_args()

    # Parse cluster nodes from command line
    cluster_nodes = []
    for node in args.cluster_nodes.split(","):
        host, port = node.strip().split(":")
        cluster_nodes.append((host, int(port)))

    st.set_page_config(page_title="Secure Chat", layout="wide")

    init_session_state()

    # Store cluster configuration in session state
    if "cluster_nodes" not in st.session_state:
        st.session_state.cluster_nodes = cluster_nodes

    # Automatic connection from command line arguments if provided.
    if not st.session_state.server_connected and args.host and args.port:
        st.session_state.server_host = args.host
        st.session_state.server_port = args.port
        temp_client = ChatClient(
            username="",
            host=args.host,
            port=args.port,
            cluster_nodes=st.session_state.cluster_nodes,
        )
        if temp_client.connect():
            if check_and_reconnect_leader(temp_client):
                st.session_state.server_connected = True
                st.success(
                    f"Automatically connected to leader at {temp_client.host}:{temp_client.port}"
                )
            else:
                st.error("Failed to determine leader server.")
        else:
            st.error(
                f"Failed to connect automatically to {args.host}:{args.port} (from command line)."
            )
        temp_client.close()
        st.rerun()

    if not st.session_state.logged_in:
        render_login_page()
    else:
        # Check if we need to reconnect to the leader
        if st.session_state.client is not None:
            if not check_and_reconnect_leader(st.session_state.client):
                st.error("Lost connection to leader. Please try reconnecting.")
                st.session_state.client_connected = False
                st.rerun()

        # If we do have a connected client and user is logged in, go to chat UI
        if st.session_state.client_connected:
            try:
                # Process any new messages
                process_incoming_realtime_messages()
            except Exception as e:
                st.warning(f"An error occurred while processing messages: {e}")

            # Add manual refresh button in the sidebar
            with st.sidebar:
                if st.button("🔄 Refresh"):
                    st.session_state.fetch_chat_partners = True
                    st.rerun()

            render_sidebar()
            render_chat_page_with_deletion()
        else:
            st.error("Client is not connected. Please try logging in again.")


if __name__ == "__main__":
    main()
