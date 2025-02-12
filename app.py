# app.py
import datetime
import os
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import time
import threading
import queue
from client import ChatClient
from protocols.base import Message, MessageType

def init_session_state():
    if "client" not in st.session_state:
        st.session_state.client = None
    if "username" not in st.session_state:
        st.session_state.username = None
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "current_chat" not in st.session_state:
        st.session_state.current_chat = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "page" not in st.session_state:
        st.session_state.page = 1
    if "search_results" not in st.session_state:
        st.session_state.search_results = []
    if "new_message" not in st.session_state:
        st.session_state.new_message = ""
    if "lock" not in st.session_state:
        st.session_state.lock = threading.Lock()

    if "conversation_offset" not in st.session_state:
        st.session_state.conversation_offset = 0
    if "initialized_chat" not in st.session_state:
        st.session_state.initialized_chat = None

def render_login_page():
    st.title("Secure Chat - Login")

    col1, col2 = st.columns(2)
    with col1:
        st.header("Login")
        username_login = st.text_input("Username", key="login_username")
        password_login = st.text_input("Password", type="password", key="login_password")
        if st.button("Login"):
            if username_login and password_login:
                st.session_state.client.username = username_login
                success = st.session_state.client.login(password_login)
                if success:
                    st.session_state.username = username_login
                    st.session_state.logged_in = True
                    st.success("Logged in successfully!")
                    st.rerun()
                else:
                    st.error("Login failed. Please check your credentials.")
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
                st.session_state.client.username = username_reg
                success = st.session_state.client.create_account(password_reg)
                if success:
                    st.session_state.username = username_reg
                    st.session_state.logged_in = True
                    st.success("Account created and logged in successfully!")
                    st.rerun()
                else:
                    st.error("Account creation failed. Username may already exist.")

def fetch_accounts(pattern: str = "", page: int = 1):
    response = st.session_state.client.list_accounts_sync(pattern, page)
    if response and response.type == MessageType.SUCCESS:
        st.session_state.search_results = response.payload.get("users", [])
        st.success(f"Found {len(st.session_state.search_results)} user(s).")
    else:
        st.session_state.search_results = []
        st.warning("No users found or an error occurred.")

def fetch_chat_partners():
    """
    Wrapper that calls client.list_chat_partners_sync(),
    returns the list of partner names or an empty list.
    """
    resp = st.session_state.client.list_chat_partners_sync()
    if resp and resp.type == MessageType.SUCCESS:
        return resp.payload.get("chat_partners", [])
    return []

def load_conversation(partner, offset=0, limit=20, load_older=False):
    resp = st.session_state.client.read_conversation_sync(partner, offset=offset, limit=limit)
    if resp and resp.type == MessageType.SUCCESS:
        db_msgs = resp.payload.get("messages", [])
        # db_msgs is newest->oldest for this chunk
        db_msgs.reverse()  # oldest->newest

        new_messages = []
        for m in db_msgs:
            new_messages.append({
                "sender": m["from"],
                "text": m["content"],
                "timestamp": m["timestamp"]
            })

        if load_older:
            # If user clicked "Load older", prepend these older messages
            # above the existing ones
            st.session_state.messages = new_messages + st.session_state.messages
        else:
            # first load => just replace
            st.session_state.messages = new_messages
    else:
        st.session_state.messages = []



def process_incoming_realtime_messages():
    """
    Process any real-time push messages the server sends us.
    If a new message arrives from 'sender' and our current_chat == sender,
    we append it so we see it live.
    """
    client = st.session_state.client
    while not client.incoming_messages_queue.empty():
        msg = client.incoming_messages_queue.get()
        if msg.type == MessageType.SEND_MESSAGE:
            sender = msg.sender
            text = msg.payload.get("text", "")
            timestamp = msg.timestamp
            with st.session_state.lock:
                if st.session_state.current_chat == sender:
                    st.session_state.messages.append({
                        "sender": sender,
                        "text": text,
                        "timestamp": timestamp,
                    })
            st.success(f"New message from {sender}: {text}")

def render_sidebar():
    st.sidebar.title("Menu")
    st.sidebar.subheader(f"Logged in as: {st.session_state.username}")

    chat_partners = fetch_chat_partners()

    with st.sidebar.expander("Existing Chats", expanded=True):
        if chat_partners:
            for partner in chat_partners:
                if partner != st.session_state.username:
                    if st.button(partner, key=f"chat_partner_{partner}"):
                        st.session_state.initialized_chat = partner
                        st.session_state.conversation_offset = 0
                        load_conversation(partner, offset=0, limit=20, load_older=False)
                        st.session_state.current_chat = partner
                        st.rerun()
        else:
            st.write("No existing chats found.")

    with st.sidebar.expander("Find New Users", expanded=False):
        pattern = st.text_input("Search by username", key="search_pattern")
        if st.button("Search", key="search_button"):
            fetch_accounts(pattern, st.session_state.page)

        if st.session_state.search_results:
            st.write("**Search Results:**")
            for user in st.session_state.search_results:
                if user != st.session_state.username:
                    if st.button(user, key=f"user_{user}"):
                        st.session_state.initialized_chat = user
                        st.session_state.conversation_offset = 0
                        load_conversation(user, offset=0, limit=20, load_older=False)
                        st.session_state.current_chat = user
                        st.rerun()

    with st.sidebar.expander("Account Options", expanded=False):
        if st.button("Delete Account"):
            confirm = st.checkbox("Are you sure you want to delete your account?",
                                  key="confirm_delete")
            if confirm:
                success = st.session_state.client.delete_account()
                if success:
                    st.session_state.logged_in = False
                    st.session_state.username = None
                    st.session_state.current_chat = None
                    st.session_state.messages = []
                    st.success("Account deleted successfully.")
                    st.rerun()
                else:
                    st.error("Failed to delete account.")

def render_chat_page():
    """
    Renders the main chat area (center of the page).
    The sidebar is rendered separately by render_sidebar().
    """
    st.title("Secure Chat")

    if st.session_state.current_chat:
        partner = st.session_state.current_chat

        st.subheader(f"Chat with {partner}")

        if st.session_state.messages:
            for msg in st.session_state.messages:
                sender = msg.get("sender")
                text = msg.get("text")
                ts = msg.get("timestamp", time.time())

                if isinstance(ts, str):
                    try:
                        dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                        epoch = dt.timestamp()
                    except ValueError:
                        epoch = time.time()
                else:
                    epoch = float(ts)

                formatted_timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(epoch))

                if sender == st.session_state.username:
                    st.markdown(f"**You** [{formatted_timestamp}]: {text}")
                else:
                    st.markdown(f"**{sender}** [{formatted_timestamp}]: {text}")
        else:
            st.info("No messages to display. Type below to send one.")

        if st.button("Load older messages"):
            st.session_state.conversation_offset += 20
            load_conversation(
                partner,
                offset=st.session_state.conversation_offset,
                limit=20,
                load_older=True
            )
            st.rerun()

        new_msg = st.text_area("Type your message", key="new_message")
        if st.button("Send"):
            if new_msg.strip() == "":
                st.warning("Cannot send an empty message.")
            else:
                success = st.session_state.client.send_message(partner, new_msg)
                if success:
                    st.success("Message sent.")
                    with st.session_state.lock:
                        st.session_state.messages.append({
                            "sender": st.session_state.username,
                            "text": new_msg,
                            "timestamp": time.time(),
                        })
                    st.rerun()
                else:
                    st.error("Failed to send message.")
    else:
        st.info("Select a user from the sidebar or search to begin chat.")

def main():
    st.set_page_config(page_title="Secure Chat", layout="wide")

    st_autorefresh(interval=3000, key="auto_refresh_chat")

    init_session_state()

    if not st.session_state.client:
        host = "127.0.0.1"
        port = 54400
        protocol = "J"  # or "B" for binary
        st.session_state.client = ChatClient(username="", protocol_type=protocol,
                                             host=host, port=port)
        connected = st.session_state.client.connect()
        if not connected:
            st.error("Failed to connect to server.")
            return

    if not st.session_state.logged_in:
        render_login_page()
    else:
        process_incoming_realtime_messages()

        render_sidebar()

        render_chat_page()

if __name__ == "__main__":
    main()
