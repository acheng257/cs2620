import argparse
import threading
import time
from typing import Dict, List, Optional, Tuple

import streamlit as st
from streamlit_autorefresh import st_autorefresh

# Import your gRPC-based ChatClient.
from src.chat_grpc_client import ChatClient
from src.database.db_manager import DatabaseManager
import grpc


def init_session_state() -> None:
    """Initialize all necessary session states."""
    if "username" not in st.session_state:
        st.session_state.username = None
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "current_chat" not in st.session_state:
        st.session_state.current_chat = None
    if "displayed_messages" not in st.session_state:
        st.session_state.displayed_messages = []
    if "all_messages" not in st.session_state:
        st.session_state.all_messages = []  # all messages received via ReadMessages
    if "search_results" not in st.session_state:
        st.session_state.search_results = []
    if "unread_map" not in st.session_state:
        st.session_state.unread_map = {}  # {partner_username: unread_count}
    if "client_connected" not in st.session_state:
        st.session_state.client_connected = False
    if "server_host" not in st.session_state:
        st.session_state.server_host = ""
    if "server_port" not in st.session_state:
        st.session_state.server_port = 50051  # default gRPC port
    if "server_connected" not in st.session_state:
        st.session_state.server_connected = False
    if "client" not in st.session_state:
        st.session_state.client = None
    if "error_message" not in st.session_state:
        st.session_state.error_message = ""


def get_chat_client() -> Optional[ChatClient]:
    """
    Return the connected ChatClient if logged in.
    """
    if st.session_state.logged_in and st.session_state.client_connected and st.session_state.client:
        return st.session_state.client
    st.error("Chat client is not connected.")
    return None


def render_login_page() -> None:
    """Render the login and account creation interface using gRPC methods."""
    st.title("Secure Chat - Login / Sign Up")
    if st.session_state.error_message:
        st.error(st.session_state.error_message)

    with st.expander("Server Settings", expanded=True):
        server_host = st.text_input("Server Host", value=st.session_state.server_host, key="server_host_input")
        server_port = st.number_input(
            "Server Port",
            min_value=1,
            max_value=65535,
            value=st.session_state.server_port,
            key="server_port_input",
        )
        if st.button("Connect to Server"):
            if not server_host:
                st.warning("Please enter the server's IP address.")
            else:
                st.session_state.server_host = server_host
                st.session_state.server_port = int(server_port)
                try:
                    # Create a temporary client to test connectivity.
                    temp_client = ChatClient(username="", host=st.session_state.server_host, port=st.session_state.server_port)
                    if temp_client:
                        st.session_state.server_connected = True
                        st.success("Connected to server successfully. You can now log in or create an account.")
                    else:
                        st.session_state.error_message = "Failed to connect to the server."
                    temp_client.close()
                except Exception as e:
                    st.session_state.error_message = f"Error connecting to server: {e}"

    st.markdown("---")
    if not st.session_state.server_connected:
        st.warning("Please connect to the server before logging in or creating an account.")
        return

    # Enter username (used for both login and signup).
    if not st.session_state.username:
        with st.form("username_form"):
            username = st.text_input("Enter your username", key="username_input")
            if st.form_submit_button("Continue") and username.strip():
                st.session_state.username = username.strip()
        return

    username = st.session_state.username

    # Check account existence using a dummy login (with a known dummy password).
    account_exists = False
    try:
        temp_client = ChatClient(username=username, host=st.session_state.server_host, port=st.session_state.server_port)
        # Attempt dummy login to check if the account exists.
        if not temp_client.login("dummy_password"):
            account_exists = False
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNAUTHENTICATED and "Invalid password" in e.details():
            # The account exists, but the dummy password is invalid.
            account_exists = True
        else:
            print(f"Error checking account existence: {e}")
            account_exists = False
    finally:
        temp_client.close()


    if account_exists:
        st.info("Account found. Please log in by entering your password.")
        with st.form("login_form"):
            password = st.text_input("Password", type="password", key="login_password")
            if st.form_submit_button("Login"):
                client = ChatClient(username=username, host=st.session_state.server_host, port=st.session_state.server_port)
                if client.login(password):
                    st.session_state.logged_in = True
                    st.session_state.client = client
                    st.session_state.client_connected = True
                    # Start the gRPC message-reading thread.
                    threading.Thread(target=client.read_messages, daemon=True).start()
                    st.success("Logged in successfully!")
                else:
                    st.error("Incorrect password. Please try again.")
    else:
        st.info("No account found for this username. Please create an account.")
        with st.form("signup_form"):
            password = st.text_input("Create Password", type="password", key="signup_password")
            confirm = st.text_input("Confirm Password", type="password", key="confirm_password")
            if st.form_submit_button("Create Account"):
                if password != confirm:
                    st.error("Passwords do not match.")
                elif len(password) < 6:
                    st.error("Password must be at least 6 characters long.")
                else:
                    client = ChatClient(username=username, host=st.session_state.server_host, port=st.session_state.server_port)
                    client.create_account(password)
                    # After account creation, try logging in.
                    if client.login(password):
                        st.session_state.logged_in = True
                        st.session_state.client = client
                        st.session_state.client_connected = True
                        threading.Thread(target=client.read_messages, daemon=True).start()
                        st.success("Account created and logged in successfully!")
                    else:
                        st.error("Account creation failed. Username may already exist.")

    if st.button("Change Username"):
        st.session_state.username = None


def fetch_accounts(pattern: str = "", page: int = 1) -> None:
    client = get_chat_client()
    if client:
        try:
            response = client.list_accounts(pattern, page)
            # Expect the response payload to contain a key 'users'
            st.session_state.search_results = response.payload.get("users", [])
        except Exception as e:
            st.warning(f"Error fetching accounts: {e}")


def fetch_chat_partners() -> Tuple[List[str], Dict[str, int]]:
    client = get_chat_client()
    if client:
        try:
            response = client.list_chat_partners()
            partners = response.get("chat_partners", [])
            unread_map = response.get("unread_map", {})
            st.session_state.unread_map = unread_map
            return partners, unread_map
        except Exception as e:
            st.error(f"Error fetching chat partners: {e}")
    return [], {}


# def load_conversation(partner: str) -> None:
#     """
#     Since no separate RPC for conversation history exists,
#     filter all received messages for those exchanged with the specified partner.
#     """
#     username = st.session_state.username
#     conv_msgs = [
#         msg
#         for msg in st.session_state.all_messages
#         if (msg.get("sender") == partner and msg.get("recipient") == username)
#         or (msg.get("sender") == username and msg.get("recipient") == partner)
#     ]
#     conv_msgs.sort(key=lambda x: x.get("timestamp", 0))
#     st.session_state.displayed_messages = conv_msgs
def load_conversation(partner: str) -> None:
    client = get_chat_client()
    if client:
        messages = client.read_conversation(partner, offset=0, limit=50)
        # Sort messages chronologically (if needed)
        messages.sort(key=lambda m: m.get("timestamp", 0))
        st.session_state.displayed_messages = messages


def process_incoming_realtime_messages() -> None:
    """
    Check the client’s incoming_messages_queue (populated by the read_messages thread)
    and add any new messages to st.session_state.all_messages.
    """
    client = get_chat_client()
    if client and hasattr(client, "incoming_messages_queue"):
        while not client.incoming_messages_queue.empty():
            msg = client.incoming_messages_queue.get()
            # Here we assume that msg is a ChatMessage (protobuf) and convert it to a dict.
            st.session_state.all_messages.append({
                "sender": msg.sender,
                "recipient": msg.recipient,
                "text": msg.payload.get("text", ""),
                "timestamp": msg.timestamp,
            })
            # Update unread count if not in current chat.
            if st.session_state.current_chat != msg.sender:
                st.session_state.unread_map[msg.sender] = st.session_state.unread_map.get(msg.sender, 0) + 1


def render_sidebar() -> None:
    st.sidebar.title("Menu")
    st.sidebar.subheader(f"Logged in as: {st.session_state.username}")

    if st.sidebar.button("Refresh Chats"):
        st.session_state.unread_map = {}

    partners, _ = fetch_chat_partners()
    with st.sidebar.expander("Existing Chats", expanded=True):
        if partners:
            for partner in partners:
                if partner != st.session_state.username:
                    unread = st.session_state.unread_map.get(partner, 0)
                    label = f"{partner}" + (f" ({unread} unread)" if unread > 0 else "")
                    if st.button(label, key=f"chat_{partner}"):
                        st.session_state.current_chat = partner
                        load_conversation(partner)
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
                        load_conversation(user)
                        st.rerun()

    with st.sidebar.expander("Account Options", expanded=False):
        st.write("---")
        if st.button("Delete Account"):
            if st.button("Confirm Delete"):
                client = get_chat_client()
                if client and client.delete_account():
                    st.session_state.logged_in = False
                    st.session_state.username = None
                    st.session_state.client = None
                    st.session_state.client_connected = False
                    st.success("Account deleted successfully.")
                    st.rerun()
                else:
                    st.error("Failed to delete account.")


def render_chat_page() -> None:
    st.title("Secure Chat")
    if st.session_state.current_chat:
        partner = st.session_state.current_chat
        st.subheader(f"Chat with {partner}")
        load_conversation(partner)
        messages = st.session_state.displayed_messages

        for msg in messages:
            # ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(msg.get("timestamp", time.time())))
            ts = msg.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))

            sender = "You" if msg.get("sender") == st.session_state.username else msg.get("sender")
            st.markdown(f"**{sender}** [{ts}]: {msg.get('text')}")

        new_msg = st.text_area("Type your message", key="new_message")
        if st.button("Send"):
            if new_msg.strip():
                client = get_chat_client()
                if client and client.send_message(partner, new_msg):
                    st.success("Message sent.")
                    st.session_state.all_messages.append({
                        "sender": st.session_state.username,
                        "recipient": partner,
                        "text": new_msg,
                        "timestamp": time.time()
                    })
                    load_conversation(partner)
                    st.rerun()
                else:
                    st.error("Failed to send message.")
            else:
                st.warning("Message cannot be empty.")
    else:
        st.info("Select a user from the sidebar to begin chatting.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="", help="Server host address")
    parser.add_argument("--port", type=int, default=50051, help="Server port number")
    args = parser.parse_args()

    st.set_page_config(page_title="Secure Chat", layout="wide")
    st_autorefresh(interval=3000, key="auto_refresh_chat")
    init_session_state()

    if args.host:
        st.session_state.server_host = args.host
    if args.port:
        st.session_state.server_port = args.port

    # Auto-connect if host is provided.
    if not st.session_state.server_connected:
        try:
            temp_client = ChatClient(username="", host=st.session_state.server_host, port=st.session_state.server_port)
            if temp_client:
                st.session_state.server_connected = True
                st.success("Automatically connected to the server.")
            else:
                st.session_state.error_message = "Failed to auto-connect to the server."
            temp_client.close()
        except Exception as e:
            st.session_state.error_message = f"Auto connection error: {e}"

    if not st.session_state.logged_in:
        render_login_page()
    else:
        # Process incoming messages from the gRPC streaming RPC.
        process_incoming_realtime_messages()
        render_sidebar()
        render_chat_page()


if __name__ == "__main__":
    main()
