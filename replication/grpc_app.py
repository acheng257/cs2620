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


# Attach this new method to ChatClient (monkey-patching for simplicity)
ChatClient.get_leader = get_leader


def init_session_state() -> None:
    """Initialize all necessary session states."""
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


def check_and_reconnect_leader(client: ChatClient) -> bool:
    """
    Check if the current connection is to the leader.
    Returns True if we're connected to the leader (either already or after reconnecting),
    False otherwise.
    """
    # First try current connection
    try:
        leader = client.get_leader()
        if leader:
            leader_host, leader_port = leader
            if leader_host != client.host or leader_port != client.port:
                print(f"Detected leader change to {leader_host}:{leader_port}, reconnecting...")
                client.host = leader_host
                client.port = leader_port
                if client.connect():
                    print("Successfully reconnected to new leader")
                    if client.read_thread:
                        client.read_thread = None
                    client.start_read_thread()
                    return True
            else:
                return True  # Already connected to leader
    except Exception as e:
        print(f"Current connection failed: {e}")

    # If current connection failed, try all known cluster nodes
    print("Trying all known cluster nodes to find leader...")
    for node_host, node_port in client.cluster_nodes:
        if (node_host, node_port) == (
            client.host,
            client.port,
        ):  # Skip current node as we know it failed
            continue
        try:
            print(f"Trying node at {node_host}:{node_port}...")
            temp_client = ChatClient(
                username="", host=node_host, port=node_port, cluster_nodes=client.cluster_nodes
            )
            if temp_client.connect(timeout=1):  # Short timeout for discovery
                leader = temp_client.get_leader()
                temp_client.close()
                if leader:
                    leader_host, leader_port = leader
                    print(
                        f"Found leader through node {node_host}:{node_port}: {leader_host}:{leader_port}"
                    )
                    # Update client connection
                    client.host = leader_host
                    client.port = leader_port
                    if client.connect():
                        print("Successfully connected to leader")
                        if client.read_thread:
                            client.read_thread = None
                        client.start_read_thread()
                        return True
        except Exception as e:
            print(f"Failed to check node at {node_host}:{node_port}: {e}")
            continue

    print("Could not find leader through any known nodes")
    return False


def get_chat_client() -> Optional[ChatClient]:
    """
    Return the connected ChatClient if logged in and connected to the leader, else None.
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
    # If the user is already logged in, don't render the login page.
    if st.session_state.logged_in:
        return

    st.title("Secure Chat - Login / Sign Up")

    if st.session_state.error_message:
        st.error(st.session_state.error_message)

    with st.expander("Server Settings", expanded=True):
        if st.session_state.server_connected:
            st.markdown("✅ Connected to leader server:")
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

    # If no pending username is set, prompt for one.
    if not st.session_state.pending_username:
        with st.form("enter_username_form"):
            username = st.text_input("Enter your unique username", key="username_input")
            if st.form_submit_button("Continue") and username.strip():
                st.session_state.pending_username = username.strip()
        return

    username = st.session_state.pending_username

    # Check account existence using a dummy password attempt.
    # (If the account does not exist, the server will return an error that includes
    # "does not exist" or "will be created automatically".)
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
        with st.form("login_form"):
            password = st.text_input("Password", type="password", key="login_password")
            if st.form_submit_button("Login"):
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
                        st.success("Logged in successfully!")
                        client.start_read_thread()
                        client.start_leader_check_thread()  # Start leader check thread
                    else:
                        if error and (
                            "does not exist" in error.lower()
                            or "will be created automatically" in error.lower()
                        ):
                            st.info("Account does not exist. Creating account automatically...")
                            created = client.create_account_sync(password)
                            if created:
                                st.session_state.username = username
                                st.session_state.logged_in = True
                                st.session_state.client = client
                                st.session_state.client_connected = True
                                st.session_state.global_message_limit = 50
                                st.success("Account created and logged in successfully!")
                                client.start_read_thread()
                                client.start_leader_check_thread()  # Start leader check thread
                                st.session_state.pending_username = ""  # Clear pending username
                                st.rerun()  # Update UI state immediately.
                            else:
                                st.error("Failed to create account.")
                        else:
                            st.error(f"Login failed: {error}")
                else:
                    st.error("Failed to connect to the server.")
    else:
        st.info("No account found. Please create an account by choosing a password.")
        with st.form("signup_form"):
            password1 = st.text_input("Enter Password", type="password", key="signup_password1")
            password2 = st.text_input("Confirm Password", type="password", key="signup_password2")
            if st.form_submit_button("Create Account"):
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
                            st.success("Account created and logged in successfully!")
                            client.start_read_thread()
                            client.start_leader_check_thread()  # Start leader check thread
                            st.session_state.pending_username = ""  # Clear pending username
                            st.rerun()  # Immediately re-run to reflect logged-in state.
                        else:
                            st.error("Account creation failed. Username may already exist.")
                    else:
                        st.error("Connection to server failed.")

    if st.button("Change Username"):
        st.session_state.pending_username = ""


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
    if "chat_partners" in st.session_state and st.session_state.chat_partners:
        return st.session_state.chat_partners, st.session_state.unread_map

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
    client = get_chat_client()
    if client:
        new_partner_detected = False
        new_message_received = False
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
                        st.session_state.messages.append(new_message)
                        new_message_received = True
                        if (
                            "conversations" in st.session_state
                            and st.session_state.current_chat in st.session_state.conversations
                        ):
                            conv = st.session_state.conversations[st.session_state.current_chat]
                            conv["displayed_messages"].append(new_message)
                            if len(conv["displayed_messages"]) > conv["limit"]:
                                conv["displayed_messages"] = conv["displayed_messages"][
                                    -conv["limit"] :
                                ]
                    else:
                        st.session_state.unread_map[sender] = (
                            st.session_state.unread_map.get(sender, 0) + 1
                        )
                        if "chat_partners" not in st.session_state:
                            st.session_state.chat_partners = []
                        if sender not in st.session_state.chat_partners:
                            st.session_state.chat_partners.append(sender)
                            new_partner_detected = True
                st.success(f"New message from {sender}: {text}")
        if new_partner_detected or new_message_received:
            st.rerun()


def render_sidebar() -> None:
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


def render_chat_page_with_deletion() -> None:
    st.title("Secure Chat")

    if st.session_state.current_chat:
        partner = st.session_state.current_chat
        st.subheader(f"Chat with {partner}")

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

        if not conv["displayed_messages"]:
            load_conversation(partner, conv["offset"], conv["limit"])
            conv["displayed_messages"] = st.session_state.displayed_messages.copy()

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
            st.session_state.scroll_to_bottom = True
            st.session_state.scroll_to_top = False
            db_manager = DatabaseManager()
            db_manager.update_chat_message_limit(st.session_state.username, partner, new_limit)

        messages = conv["displayed_messages"]

        with st.container():
            with st.form("select_messages_form"):
                selected_message_ids = []
                for msg in messages:
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
            st.session_state.scroll_to_top = True
            st.session_state.scroll_to_bottom = False

        if st.session_state.get("clear_message_area", False):
            st.session_state["input_text"] = ""
            st.session_state["clear_message_area"] = False

        new_msg = st.text_area("Type your message", key="input_text", height=100)
        if st.button("Send"):
            if new_msg.strip() == "":
                st.warning("Cannot send an empty message.")
            else:
                client = get_chat_client()
                if client:
                    try:
                        response = client.send_message_sync(partner, new_msg)
                        if (
                            MessageToDict(response.payload).get("text", "").lower().find("success")
                            != -1
                        ):
                            st.success("Message sent.")
                            st.session_state["clear_message_area"] = True
                            load_conversation(partner, 0, conv["limit"])
                            conv["offset"] = 0
                            conv["displayed_messages"] = st.session_state.displayed_messages.copy()
                        else:
                            st.error("Failed to send message.")
                    except Exception as e:
                        st.error(f"An error occurred while sending the message: {e}")
                else:
                    st.error("Client is not connected.")
    else:
        st.info("Select a user from the sidebar or search to begin chat.")


def main() -> None:
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
    st_autorefresh(interval=1000, key="auto_refresh_chat")  # Refresh every second

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
                process_incoming_realtime_messages()
            except Exception as e:
                st.warning(f"An error occurred while processing messages: {e}")
            render_sidebar()
            render_chat_page_with_deletion()
        else:
            st.error("Client is not connected. Please try logging in again.")


if __name__ == "__main__":
    main()
