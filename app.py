import datetime
import threading
import time
from typing import Dict, List, Tuple, Optional

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from client import ChatClient
from protocols.base import MessageType


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
        st.session_state.client_connected = False  # Track user authentication status
    if "server_host" not in st.session_state:
        st.session_state.server_host = ""  # Initialize as empty to enforce user input
    if "server_port" not in st.session_state:
        st.session_state.server_port = 54400  # Default port; users can change as needed
    if "server_connected" not in st.session_state:
        st.session_state.server_connected = False  # Track server connection status
    if "client" not in st.session_state:
        st.session_state.client = None  # Initialize client as None
    if "error_message" not in st.session_state:
        st.session_state.error_message = ""  # To store and display error messages


def get_chat_client() -> Optional[ChatClient]:
    """
    Return the connected ChatClient if logged in, else None.
    """
    if st.session_state.logged_in and st.session_state.client_connected and st.session_state.client:
        return st.session_state.client
    return None


def render_login_page() -> None:
    """Render the login and account creation interface."""
    st.title("Secure Chat - Login")

    # Display persistent error message if exists
    if st.session_state.error_message:
        st.error(st.session_state.error_message)

    # Server Connection Settings
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
                # Update session state with server details
                st.session_state.server_host = server_host
                st.session_state.server_port = int(server_port)
                st.session_state.server_connected = False  # Reset server connection status
                st.session_state.client = None  # Reset client to force reinitialization
                st.session_state.client_connected = False
                st.session_state.error_message = ""  # Clear previous error messages

                # Attempt to connect to the server without a username
                try:
                    client = ChatClient(
                        username="",  # No username yet
                        protocol_type="J" if st.session_state.protocol == "JSON" else "B",
                        host=st.session_state.server_host,
                        port=st.session_state.server_port,
                    )
                    connected = client.connect()
                    if connected:
                        st.session_state.server_connected = True
                        st.session_state.client_connected = False  # Not authenticated yet
                        st.session_state.client = None  # Disregard the unauthenticated client
                        st.success("Connected to server successfully. You can now log in or create an account.")
                    else:
                        st.session_state.server_connected = False
                        st.session_state.client_connected = False
                        st.session_state.client = None
                        st.session_state.error_message = "Failed to connect to the server. Please check the IP address and port."
                except Exception as e:
                    st.session_state.server_connected = False
                    st.session_state.client_connected = False
                    st.session_state.client = None
                    st.session_state.error_message = f"An error occurred while connecting to the server: {e}"
                # No rerun here to allow error_message to persist

    st.markdown("---")

    # Protocol Selection
    protocol_options = ["JSON", "Binary"]
    selected_protocol = st.selectbox(
        "Select Protocol",
        options=protocol_options,
        index=protocol_options.index(st.session_state.protocol),
        key="protocol_selection",
    )

    if selected_protocol != st.session_state.protocol:
        # If protocol changes, reset the client and related session states
        st.session_state.protocol = selected_protocol
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.current_chat = None
        st.session_state.messages = []
        st.session_state.unread_map = {}
        st.session_state.client = None
        st.session_state.client_connected = False
        st.session_state.server_connected = False
        st.session_state.error_message = ""  # Clear error messages
        st.warning("Protocol changed. Please reconnect to the server.")
        # No rerun; user can reconnect manually

    # Ensure the server is connected before allowing login or account creation
    if not st.session_state.server_connected:
        st.warning("Please connect to the server before logging in or creating an account.")
        return

    # Login and Create Account Sections
    col1, col2 = st.columns(2)
    with col1:
        st.header("Login")
        username_login = st.text_input("Username", key="login_username")
        password_login = st.text_input("Password", type="password", key="login_password")
        if st.button("Login"):
            if username_login and password_login:
                # Initialize a new ChatClient for login
                try:
                    protocol_map = {"JSON": "J", "Binary": "B"}
                    protocol_type = protocol_map.get(st.session_state.protocol, "J")
                    client = ChatClient(
                        username=username_login,
                        protocol_type=protocol_type,
                        host=st.session_state.server_host,
                        port=st.session_state.server_port,
                    )
                    connected = client.connect()
                    if connected:
                        success = client.login(password_login)
                        if success:
                            st.session_state.username = username_login
                            st.session_state.logged_in = True
                            st.session_state.client = client
                            st.session_state.client_connected = True
                            st.session_state.error_message = ""  # Clear error messages
                            st.success("Logged in successfully!")
                        else:
                            st.session_state.error_message = "Login failed. Please check your credentials."
                            client.close()
                    else:
                        st.session_state.error_message = "Failed to connect to the server. Please check the IP address and port."
                except Exception as e:
                    st.session_state.error_message = f"An error occurred during login: {e}"
                # No rerun to allow error_message to persist
            else:
                st.warning("Please enter both username and password.")

    with col2:
        st.header("Create Account")
        username_reg = st.text_input("New Username", key="reg_username")
        password_reg = st.text_input("New Password", type="password", key="reg_password")
        password_reg2 = st.text_input("Confirm Password", type="password", key="reg_password2")
        if st.button("Create Account"):
            if not username_reg or not password_reg or not password_reg2:
                st.warning("Please fill out all fields.")
            elif password_reg != password_reg2:
                st.warning("Passwords do not match.")
            elif len(password_reg) < 6:
                st.warning("Password must be at least 6 characters long.")
            else:
                # Initialize a new ChatClient for account creation
                try:
                    protocol_map = {"JSON": "J", "Binary": "B"}
                    protocol_type = protocol_map.get(st.session_state.protocol, "J")
                    client = ChatClient(
                        username=username_reg,
                        protocol_type=protocol_type,
                        host=st.session_state.server_host,
                        port=st.session_state.server_port,
                    )
                    connected = client.connect()
                    if connected:
                        success = client.create_account(password_reg)
                        if success:
                            st.session_state.username = username_reg
                            st.session_state.logged_in = True
                            st.session_state.client = client
                            st.session_state.client_connected = True
                            st.session_state.error_message = ""  # Clear error messages
                            st.success("Account created and logged in successfully!")
                        else:
                            st.session_state.error_message = "Account creation failed. Username may already exist."
                            client.close()
                    else:
                        st.session_state.error_message = "Failed to connect to the server. Please check the IP address and port."
                except Exception as e:
                    st.session_state.error_message = f"An error occurred during account creation: {e}"
                # No rerun to allow error_message to persist


def fetch_accounts(pattern: str = "", page: int = 1) -> None:
    """Fetch and display user accounts matching a search pattern."""
    client = get_chat_client()
    if client:
        try:
            response = client.list_accounts_sync(pattern, page)
            if response and response.type == MessageType.SUCCESS:
                st.session_state.search_results = response.payload.get("users", [])
                st.success(f"Found {len(st.session_state.search_results)} user(s).")
            else:
                st.session_state.search_results = []
                st.warning("No users found or an error occurred.")
        except Exception as e:
            st.warning(f"An error occurred while fetching accounts: {e}")
    else:
        st.warning("Client is not connected.")


def fetch_chat_partners() -> Tuple[List[str], Dict[str, int]]:
    """
    Fetch chat partners and their corresponding unread message counts.
    Updates the session state's unread_map.
    Returns:
        Tuple[List[str], Dict[str, int]]: (list_of_partners, unread_map)
    """
    client = get_chat_client()
    if client:
        try:
            resp = client.list_chat_partners_sync()
            if resp and resp.type == MessageType.SUCCESS:
                partners = resp.payload.get("chat_partners", [])
                unread_map = resp.payload.get("unread_map", {})
                st.session_state.unread_map = unread_map
                return partners, unread_map
        except Exception as e:
            st.warning(f"An error occurred while fetching chat partners: {e}")
    return [], {}


def load_conversation(partner: str, offset: int = 0, limit: int = 50) -> None:
    """
    Load and display a conversation with a specific partner.
    Resets or prepends messages based on the offset.
    Also resets the unread count for that partner.
    """
    client = get_chat_client()
    if client:
        try:
            resp = client.read_conversation_sync(partner, offset, limit)
            if resp and resp.type == MessageType.SUCCESS:
                db_msgs = resp.payload.get("messages", [])

                # Ensure messages are sorted from oldest to newest
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
                    if offset == 0:
                        # Reset messages for a new conversation
                        st.session_state.messages = new_messages
                    else:
                        # Prepend older messages
                        st.session_state.messages = new_messages + st.session_state.messages

                    st.session_state.messages_offset = offset
                    st.session_state.messages_limit = limit
                    st.session_state.scroll_to_bottom = False
                    st.session_state.scroll_to_top = True

                    # Reset unread count for this partner
                    st.session_state.unread_map[partner] = 0
            else:
                if offset == 0:
                    st.session_state.messages = []
                    st.warning("No messages found.")
                else:
                    st.warning("No more messages to load.")
        except Exception as e:
            st.warning(f"An error occurred while loading conversation: {e}")
    else:
        st.warning("Client is not connected.")


def process_incoming_realtime_messages() -> None:
    """
    Process incoming real-time messages from the server.
    Updates the chat interface and unread_map accordingly.
    """
    client = get_chat_client()
    if client:
        try:
            while not client.incoming_messages_queue.empty():
                msg = client.incoming_messages_queue.get()
                if msg.type == MessageType.SEND_MESSAGE:
                    sender = msg.sender
                    text = msg.payload.get("text", "")
                    timestamp = msg.timestamp

                    with st.session_state.lock:
                        if st.session_state.current_chat == sender:
                            # If the current chat is open, append the message and mark as read
                            st.session_state.messages.append(
                                {
                                    "sender": sender,
                                    "text": text,
                                    "timestamp": timestamp,
                                    "is_read": True,
                                    "is_delivered": True,
                                }
                            )
                            # Mark messages as read
                            client.read_conversation_sync(st.session_state.current_chat, 0, 100000)
                        else:
                            # Increment unread count for the sender
                            if sender in st.session_state.unread_map:
                                st.session_state.unread_map[sender] += 1
                            else:
                                st.session_state.unread_map[sender] = 1

                    # Display alert for new message
                    st.success(f"New message from {sender}: {text}")

                    # Trigger a rerun to update the sidebar unread counts
                    st.rerun()
        except Exception as e:
            st.warning(f"An error occurred while processing incoming messages: {e}")
    else:
        st.warning("Client is not connected.")


def render_sidebar() -> None:
    """Render the sidebar with chat partners and other options."""
    st.sidebar.title("Menu")
    st.sidebar.subheader(f"Logged in as: {st.session_state.username}")

    # Fetch chat partners and their unread counts
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
                        load_conversation(partner, 0, st.session_state.messages_limit)
                        st.session_state.scroll_to_bottom = True
                        st.session_state.scroll_to_top = False
                        # No rerun needed; Streamlit will handle it
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
                        st.session_state.messages_limit = st.session_state.messages_limit
                        load_conversation(user, 0, st.session_state.messages_limit)
                        st.session_state.scroll_to_bottom = True
                        st.session_state.scroll_to_top = False

    with st.sidebar.expander("Account Options", expanded=False):
        if st.button("Delete Account"):
            confirm = st.sidebar.checkbox(
                "Are you sure you want to delete your account?", key="confirm_delete"
            )
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
                            st.session_state.client = None
                            st.session_state.client_connected = False
                            st.session_state.server_connected = False
                            st.session_state.error_message = ""  # Clear error messages
                            st.success("Account deleted successfully.")
                        else:
                            st.error("Failed to delete account.")
                    except Exception as e:
                        st.error(f"An error occurred while deleting the account: {e}")
                else:
                    st.error("Client is not connected.")
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.current_chat = None
            st.session_state.messages = []
            st.session_state.unread_map = {}
            st.session_state.client = None
            st.session_state.client_connected = False
            st.session_state.server_connected = False
            st.session_state.error_message = ""  # Clear error messages
            st.success("Logged out successfully.")


def render_chat_page() -> None:
    """Render the main chat interface."""
    st.title("Secure Chat")

    if st.session_state.current_chat:
        partner = st.session_state.current_chat
        st.subheader(f"Chat with {partner}")

        default_limit = st.session_state.messages_limit
        new_limit = st.number_input(
            "Number of recent messages to display",
            min_value=5,
            max_value=1000,
            value=default_limit,
            step=5,
            key="messages_limit_input",
        )
        if new_limit != default_limit:
            st.session_state.messages_limit = new_limit
            st.session_state.messages_offset = 0
            load_conversation(partner, 0, new_limit)
            st.session_state.scroll_to_bottom = True
            st.session_state.scroll_to_top = False

        # Scrollable chat container
        chat_html = """
        <div style="height:400px; overflow-y:scroll; padding:0.5rem;" id="chat-container">
        """
        if st.session_state.messages:
            # Print messages from oldest to newest
            for msg in st.session_state.messages:
                sender = msg.get("sender")
                text = msg.get("text")
                ts = msg.get("timestamp", time.time())
                # is_read = msg.get("is_read", True)
                # is_delivered = msg.get("is_delivered", True)

                # Convert timestamp to a readable string
                if isinstance(ts, str):
                    try:
                        dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                        epoch = dt.timestamp()
                    except ValueError:
                        epoch = time.time()
                else:
                    try:
                        epoch = float(ts)
                    except (ValueError, TypeError):
                        epoch = time.time()

                formatted_timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))
                sender_name = "You" if sender == st.session_state.username else sender
                # read_indicator = "✓" if is_read else "✗"
                # delivered_indicator = "✓" if is_delivered else "☐"

                chat_html += (
                    f"<p><strong>{sender_name}</strong> [{formatted_timestamp}]: {text}</p>"
                )
        else:
            chat_html += "<p><em>No messages to display.</em></p>"

        chat_html += "</div>"

        # Scroll to top after loading more
        if st.session_state.scroll_to_top:
            scroll_js = """
            <script>
                setTimeout(function(){
                    var objDiv = document.getElementById("chat-container");
                    objDiv.scrollTop = 0;
                }, 0);
            </script>
            """
            st.components.v1.html(scroll_js, height=0)
        elif st.session_state.scroll_to_bottom:
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

        # Load More Messages Button
        if st.button("Load More Messages"):
            new_offset = st.session_state.messages_offset + st.session_state.messages_limit
            load_conversation(partner, new_offset, st.session_state.messages_limit)
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
                        success = client.send_message(st.session_state.current_chat, new_msg)
                        if success:
                            st.success("Message sent.")
                            st.session_state["clear_message_area"] = True

                            with st.session_state.lock:
                                st.session_state.messages.append(
                                    {
                                        "sender": st.session_state.username,
                                        "text": new_msg,
                                        "timestamp": time.time(),
                                        "is_read": True,
                                        "is_delivered": True,
                                    }
                                )
                                if (
                                    st.session_state.unread_map.get(st.session_state.current_chat, 0)
                                    > 0
                                ):
                                    st.session_state.unread_map[st.session_state.current_chat] = 0
                        else:
                            st.error("Failed to send message.")
                    except Exception as e:
                        st.error(f"An error occurred while sending the message: {e}")
                else:
                    st.error("Client is not connected.")
    else:
        st.info("Select a user from the sidebar or search to begin chat.")


def main() -> None:
    """Main function to run the Streamlit app."""
    st.set_page_config(page_title="Secure Chat", layout="wide")

    # Auto-refresh to check for new messages every 3 seconds
    st_autorefresh(interval=3000, key="auto_refresh_chat")

    init_session_state()

    if st.session_state.logged_in:
        # Ensure the client is initialized if the user is logged in
        client = get_chat_client()
        if not client:
            st.session_state.error_message = "Failed to initialize the chat client. Please try logging in again."
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.client_connected = False
            st.session_state.client = None
    else:
        # No action needed; login or account creation will handle client initialization
        pass

    if not st.session_state.logged_in:
        render_login_page()
    else:
        if st.session_state.client_connected:
            try:
                process_incoming_realtime_messages()
            except Exception as e:
                st.warning(f"An error occurred while processing messages: {e}")
            render_sidebar()
            render_chat_page()
        else:
            st.error("Client is not connected. Please try logging in again.")


if __name__ == "__main__":
    main()
