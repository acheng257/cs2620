import argparse
import threading
import time
from typing import Dict, List, Optional, Tuple

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from src.client import ChatClient
from src.database.db_manager import DatabaseManager
from src.protocols.base import MessageType


def init_session_state() -> None:
    """Initialize all necessary session states."""
    if "username" not in st.session_state:
        st.session_state.username = None
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "protocol" not in st.session_state:
        st.session_state.protocol = "JSON"  # Default protocol
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
        st.session_state.server_host = ""
    if "server_port" not in st.session_state:
        st.session_state.server_port = 54400
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
    # New global preference for message limit
    if "global_message_limit" not in st.session_state:
        st.session_state.global_message_limit = 50
    # Per-chat conversation data
    if "conversations" not in st.session_state:
        st.session_state.conversations = {}


def get_chat_client() -> Optional[ChatClient]:
    """
    Return the connected ChatClient if logged in, else None.
    """
    if (
        hasattr(st.session_state, "logged_in")
        and hasattr(st.session_state, "client_connected")
        and hasattr(st.session_state, "client")
        and st.session_state.logged_in
        and st.session_state.client_connected
        and isinstance(st.session_state.client, ChatClient)
    ):
        return st.session_state.client
    print("Chat client is not initialized or connected.")
    return None


def render_login_page() -> None:
    """Render the login and account creation interface with server and protocol settings."""
    st.title("Secure Chat - Login / Sign Up")

    if st.session_state.error_message:
        st.error(st.session_state.error_message)

    with st.expander("Server Settings", expanded=True):
        server_host = st.text_input(
            "Server Host",
            value=st.session_state.server_host,
            key="server_host_input",
            help="Enter the server's IP address (e.g., 192.168.1.100)",
        )
        server_port = st.number_input(
            "Server Port",
            min_value=1,
            max_value=65535,
            value=st.session_state.server_port,
            key="server_port_input",
            help="Enter the server's port number (e.g., 54400)",
        )
        if st.button("Connect to Server"):
            if not server_host:
                st.warning("Please enter the server's IP address.")
            else:
                st.session_state.server_host = server_host
                st.session_state.server_port = int(server_port)
                st.session_state.server_connected = False
                st.session_state.client = None
                st.session_state.client_connected = False
                st.session_state.error_message = ""
                try:
                    temp_client = ChatClient(
                        username="",
                        protocol_type="J" if st.session_state.protocol == "JSON" else "B",
                        host=st.session_state.server_host,
                        port=st.session_state.server_port,
                    )
                    if temp_client.connect():
                        st.session_state.server_connected = True
                        st.success(
                            "Connected to server successfully. You can now log in \
                                or create an account."
                        )
                    else:
                        st.session_state.error_message = "Failed to connect to the server. \
                            Please check the IP address and port."
                    temp_client.close()
                except Exception as e:
                    st.session_state.error_message = (
                        f"An error occurred while connecting to the server: {e}"
                    )

    protocol_options = ["JSON", "Binary"]
    selected_protocol = st.selectbox(
        "Select Protocol",
        options=protocol_options,
        index=protocol_options.index(st.session_state.protocol),
        key="protocol_selection",
    )
    if selected_protocol != st.session_state.protocol:
        st.session_state.protocol = selected_protocol
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
        st.warning("Protocol changed. Please reconnect to the server.")

    st.markdown("---")

    if not st.session_state.server_connected:
        st.warning("Please connect to the server before logging in or creating an account.")
        return

    if not st.session_state.pending_username:
        with st.form("enter_username_form"):
            username = st.text_input("Enter your unique username", key="username_input")
            if st.form_submit_button("Continue") and username.strip():
                st.session_state.pending_username = username.strip()
        return

    username = st.session_state.pending_username

    account_exists = False
    try:
        temp_client = ChatClient(
            username=username,
            protocol_type="J" if st.session_state.protocol == "JSON" else "B",
            host=st.session_state.server_host,
            port=st.session_state.server_port,
        )
        if temp_client.connect():
            success, error = temp_client.login_sync("dummy_password")
            if error and "Account does not exist" in error:
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
                    protocol_type="J" if st.session_state.protocol == "JSON" else "B",
                    host=st.session_state.server_host,
                    port=st.session_state.server_port,
                )
                if client.connect():
                    success, error = client.login_sync(password)
                    if success:
                        st.session_state.username = username
                        st.session_state.logged_in = True
                        st.session_state.client = client
                        st.session_state.client_connected = True
                        db_manager = DatabaseManager()
                        st.session_state.global_message_limit = db_manager.get_message_limit(
                            username
                        )
                        st.success("Logged in successfully!")
                    else:
                        if error and "password" in error.lower():
                            st.error("Incorrect password. Please try again.")
                        else:
                            st.error(f"Login failed: {error}")
                else:
                    st.error("Failed to connect to the server.")

    else:
        st.info(
            "No account found for this username. Please create an account by choosing a password."
        )
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
                        protocol_type="J" if st.session_state.protocol == "JSON" else "B",
                        host=st.session_state.server_host,
                        port=st.session_state.server_port,
                    )
                    if client.connect():
                        success = client.create_account(password1)
                        if success:
                            st.session_state.username = username
                            st.session_state.logged_in = True
                            st.session_state.client = client
                            st.session_state.client_connected = True
                            db_manager = DatabaseManager()
                            st.session_state.global_message_limit = db_manager.get_message_limit(
                                username
                            )
                            st.success("Account created and logged in successfully!")
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
            if response and response.type == MessageType.SUCCESS:
                st.session_state.search_results = response.payload.get("users", [])
            else:
                st.session_state.search_results = []
                st.warning("No users found or an error occurred.")
        except Exception as e:
            st.warning(f"An error occurred while fetching accounts: {e}")
    else:
        st.warning("Client is not connected.")


def fetch_chat_partners() -> Tuple[List[str], Dict[str, int]]:
    if "chat_partners" in st.session_state and st.session_state.chat_partners:
        return st.session_state.chat_partners, st.session_state.unread_map

    client = get_chat_client()
    if client:
        resp = client.list_chat_partners_sync()
        if resp and resp.type == MessageType.SUCCESS:
            partners = resp.payload.get("chat_partners", [])
            unread_map = resp.payload.get("unread_map", {})
            st.session_state.chat_partners = partners
            st.session_state.unread_map = unread_map
            return partners, unread_map
    return [], {}


def load_conversation(partner: str, offset: int = 0, limit: int = 50) -> None:
    client = get_chat_client()
    if client:
        try:
            resp = client.read_conversation_sync(partner, offset, limit)
            if resp and resp.type == MessageType.SUCCESS:
                db_msgs = resp.payload.get("messages", [])
                db_msgs_sorted = sorted(db_msgs, key=lambda x: x["timestamp"])
                new_messages = []
                for m in db_msgs_sorted:
                    new_messages.append(
                        {
                            "sender": m["from"],
                            "text": m["content"],
                            "timestamp": m["timestamp"],
                            "is_read": m.get("is_read", True),
                            "is_delivered": m.get("is_delivered", True),
                            "id": m["id"],
                        }
                    )
                with st.session_state.lock:
                    st.session_state.messages = new_messages
                    st.session_state.displayed_messages = new_messages
                    st.session_state.messages_offset = offset
                    st.session_state.messages_limit = limit
                    st.session_state.scroll_to_bottom = False
                    st.session_state.scroll_to_top = True
                    st.session_state.unread_map[partner] = 0
                st.write(f"Loaded {len(new_messages)} messages.")
        except Exception as e:
            st.warning(f"An error occurred while loading conversation: {e}")
    else:
        st.warning("Client is not connected.")


def process_incoming_realtime_messages() -> None:
    client = get_chat_client()
    if client:
        new_partner_detected = False
        new_message_received = False
        while not client.incoming_messages_queue.empty():
            msg = client.incoming_messages_queue.get()
            if msg.type == MessageType.SEND_MESSAGE:
                sender = msg.sender
                text = msg.payload.get("text", "")
                timestamp = msg.timestamp
                new_message = {
                    "sender": sender,
                    "text": text,
                    "timestamp": timestamp,
                    "is_read": True,
                    "is_delivered": True,
                }
                with st.session_state.lock:
                    if st.session_state.current_chat == sender:
                        st.session_state.messages.append(new_message)
                        new_message_received = True
                        if (
                            "conversations" in st.session_state
                            and st.session_state.current_chat in st.session_state.conversations
                        ):
                            st.session_state.conversations[st.session_state.current_chat][
                                "displayed_messages"
                            ].append(new_message)
                        client.read_conversation_sync(st.session_state.current_chat, 0, 100000)
                    else:
                        if sender in st.session_state.unread_map:
                            st.session_state.unread_map[sender] += 1
                        else:
                            st.session_state.unread_map[sender] = 1
                        if "chat_partners" in st.session_state:
                            if sender not in st.session_state.chat_partners:
                                new_partner_detected = True
                        else:
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
                        st.session_state.messages_limit = st.session_state.messages_limit
                        st.session_state.chat_partners = []
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
                                success = client.delete_account()
                                if success:
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
                        st.warning("Please check the confirmation box to delete your account.")


def render_chat_page_with_deletion() -> None:
    """Render the main chat interface with per-chat message limit persistence."""
    st.title("Secure Chat")

    if st.session_state.current_chat:
        partner = st.session_state.current_chat
        st.subheader(f"Chat with {partner}")

        # Ensure per-chat conversation data exists in session state.
        if "conversations" not in st.session_state:
            st.session_state.conversations = {}

        # If this conversation is new, retrieve its saved limit from the database.
        if partner not in st.session_state.conversations:
            db_manager = DatabaseManager()
            conv_limit = db_manager.get_chat_message_limit(st.session_state.username, partner)
            st.session_state.conversations[partner] = {
                "displayed_messages": [],
                "offset": 0,
                "limit": conv_limit,
            }
        conv = st.session_state.conversations[partner]

        # If no messages have been loaded for this chat, load them.
        if not conv["displayed_messages"]:
            load_conversation(partner, conv["offset"], conv["limit"])
            conv["displayed_messages"] = st.session_state.displayed_messages.copy()

        # Display a number input widget for the message limit (unique per chat).
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

        # Render the conversation messages and deletion checkboxes.
        with st.container():
            with st.form("select_messages_form"):
                selected_message_ids = []
                for msg in messages:
                    sender = msg.get("sender")
                    text = msg.get("text")
                    ts = msg.get("timestamp")
                    msg_id = msg.get("id")

                    # Preserve original timestamp formatting.
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
                        st.markdown(f"**{sender_name}** [{formatted_timestamp}]: {text}")
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

        # Deletion confirmation form.
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
                                st.write(
                                    f"Attempting to delete \
                                        messages: {st.session_state.pending_deletions}"
                                )
                                success = client.delete_messages_sync(
                                    st.session_state.pending_deletions
                                )
                                st.write(f"Deletion success: {success}")
                                if success:
                                    st.success("Selected messages have been deleted.")
                                    conv["displayed_messages"] = [
                                        msg
                                        for msg in conv["displayed_messages"]
                                        if msg["id"] not in st.session_state.pending_deletions
                                    ]
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

        # Render the chat container (with auto-scroll JavaScript).
        chat_html = """
        <div style="height:400px; overflow-y:scroll; padding:0.5rem;" id="chat-container">
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

        # "Load More Messages" button.
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

        # Message sending section.
        new_msg = st.text_area("Type your message", key="input_text", height=100)
        if st.button("Send"):
            if new_msg.strip() == "":
                st.warning("Cannot send an empty message.")
            else:
                client = get_chat_client()
                if client:
                    try:
                        success = client.send_message(partner, new_msg)
                        if success:
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
    # Parse command-line arguments.
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="", help="Server host address")
    parser.add_argument("--port", type=int, default=54400, help="Server port number")
    parser.add_argument(
        "--protocol",
        type=str,
        choices=["JSON", "Binary"],
        default="JSON",
        help="Communication protocol",
    )
    args, unknown = parser.parse_known_args()

    st.set_page_config(page_title="Secure Chat", layout="wide")
    st_autorefresh(interval=3000, key="auto_refresh_chat")
    init_session_state()

    # Override session state with CLI arguments if provided.
    if args.host:
        st.session_state.server_host = args.host
    if args.port:
        st.session_state.server_port = args.port
    if args.protocol:
        st.session_state.protocol = args.protocol

    # Automatically attempt to connect to the server if host is provided and not already connected.
    if st.session_state.server_host and not st.session_state.server_connected:
        try:
            temp_client = ChatClient(
                username="",
                protocol_type="J" if st.session_state.protocol == "JSON" else "B",
                host=st.session_state.server_host,
                port=st.session_state.server_port,
            )
            if temp_client.connect():
                st.session_state.server_connected = True
                st.success("Automatically connected to the server.")
            else:
                st.session_state.error_message = (
                    "Failed to connect to the server automatically. Please check the host and port."
                )
            temp_client.close()
        except Exception as e:
            st.session_state.error_message = f"Error auto connecting to server: {e}"

    if st.session_state.logged_in:
        client = get_chat_client()
        if not client:
            st.session_state.error_message = (
                "Failed to initialize the chat client. Please try logging in again."
            )
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.client_connected = False
            st.session_state.client = None
    if not st.session_state.logged_in:
        render_login_page()
    else:
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
