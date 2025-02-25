import argparse
import getpass
import sys
import threading
import time

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

from src.protocols.grpc import chat_pb2, chat_pb2_grpc


class ChatClient:
    """
    A gRPC-based client for the chat system.
    """

    def __init__(self, username: str, host: str = "127.0.0.1", port: int = 50051) -> None:
        self.username = username
        self.host = host
        self.port = port
        self.channel = grpc.insecure_channel(f"{host}:{port}")
        self.stub = chat_pb2_grpc.ChatServerStub(self.channel)
        self.logged_in = False
        self.read_thread: threading.Thread | None = None
        self.running = True

    def create_account(self, password: str) -> None:
        payload = {"username": self.username, "password": password}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.CREATE_ACCOUNT,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.CreateAccount(message)
        if response.type == chat_pb2.MessageType.SUCCESS:
            print("Account created successfully.")
        else:
            # The server may have set an error status.
            print("Account creation failed.")

    def login(self, password: str) -> bool:
        payload = {"username": self.username, "password": password}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LOGIN,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.Login(message)
        if response.type == chat_pb2.MessageType.SUCCESS:
            self.logged_in = True
            details = MessageToDict(response.payload).get("text", "")
            print(f"Login successful. {details}")
        else:
            error_text = MessageToDict(response.payload).get("text", "Login failed.")
            print(f"Login failed: {error_text}")
        return self.logged_in

    def send_message(self, recipient: str, text: str) -> bool:
        try:
            payload = {"text": text}
            message = chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.SEND_MESSAGE,
                payload=ParseDict(payload, Struct()),
                sender=self.username,
                recipient=recipient,
                timestamp=time.time(),
            )
            response = self.stub.SendMessage(message)
            if response.type == chat_pb2.MessageType.SUCCESS:
                print("Message sent successfully.")
                return True
            elif response.type == chat_pb2.MessageType.ERROR:
                error_message = MessageToDict(response.payload).get("text", "Unknown error.")
                print(f"Error sending message: {error_message}")
                return False
            else:
                print("Unexpected response from server.")
                return False
        except grpc.RpcError as e:
            print(f"RPC error while sending message: {e.details()}")
            return False

    def read_messages(self) -> None:
        """
        Listen for incoming messages using the streaming ReadMessages RPC.
        The server sends both undelivered messages and newly arriving ones.
        """
        # We use our own username as the 'recipient' so the server knows whose messages to stream.
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.READ_MESSAGES,
            payload=Struct(),  # empty payload
            sender=self.username,
            recipient=self.username,
            timestamp=time.time(),
        )
        try:
            for msg in self.stub.ReadMessages(message):
                payload_dict = MessageToDict(msg.payload)
                text = payload_dict.get("text", "")
                # Display sender and message text
                print(f"[{msg.sender}] {text}")
        except grpc.RpcError as e:
            print("Message stream closed:", e)

    def start_read_thread(self) -> None:
        if self.read_thread is None:
            self.read_thread = threading.Thread(target=self.read_messages, daemon=True)
            self.read_thread.start()

    def list_accounts(self, pattern: str = "", page: int = 1) -> None:
        payload = {"pattern": pattern, "page": page}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LIST_ACCOUNTS,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.ListAccounts(message)
        result = MessageToDict(response.payload)
        print("Accounts list:", result)

    def delete_messages(self, message_ids: list) -> None:
        payload = {"message_ids": message_ids}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.DELETE_MESSAGES,
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.DeleteMessages(message)
        if response.type == chat_pb2.MessageType.SUCCESS:
            print("Messages deleted successfully.")
        else:
            print("Failed to delete messages.")

    def delete_account(self) -> None:
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.DELETE_ACCOUNT,
            payload=Struct(),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        response = self.stub.DeleteAccount(message)
        if response.type == chat_pb2.MessageType.SUCCESS:
            print("Account deleted successfully.")
        else:
            print("Failed to delete account.")

    def close(self) -> None:
        self.running = False
        if self.channel:
            self.channel.close()

    def list_chat_partners(self):
        """
        Retrieve and return the list of chat partners using the gRPC ListChatPartners method.
        """
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.LIST_CHAT_PARTNERS,
            payload=Struct(),  # no additional data needed
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        try:
            response = self.stub.ListChatPartners(message)
            if response is None:
                print("No response received from ListChatPartners RPC.")
                return None
            result = MessageToDict(response.payload)
            print("Chat partners:", result)
            return result  # Return the result dictionary
        except grpc.RpcError as e:
            print(f"RPC error in list_chat_partners: {e.details()}")
            return None

    def read_conversation(self, partner: str, offset: int = 0, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieve the conversation history with a specific partner by calling the ReadConversation RPC.
        """
        payload = {"partner": partner, "offset": offset, "limit": limit}
        message = chat_pb2.ChatMessage(
            type=chat_pb2.MessageType.READ_MESSAGES,  # Or use a new enum value if defined
            payload=ParseDict(payload, Struct()),
            sender=self.username,
            recipient="SERVER",
            timestamp=time.time(),
        )
        try:
            response = self.stub.ReadConversation(message)
            if response and response.type == chat_pb2.MessageType.SUCCESS:
                result = MessageToDict(response.payload)
                return result.get("messages", [])
            else:
                print("Failed to read conversation.")
                return []
        except grpc.RpcError as e:
            print(f"RPC error in read_conversation: {e.details()}")
            return []

 

def get_password(prompt: str) -> str:
    while True:
        password = getpass.getpass(prompt)
        if len(password) >= 6:
            return password
        print("Password must be at least 6 characters long")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="gRPC Chat Client")
    parser.add_argument("username", help="Your chat username")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Server host to connect to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=50051,
        help="Server port to connect to (default: 50051)",
    )
    args = parser.parse_args()

    client = ChatClient(username=args.username, host=args.host, port=args.port)

    try:
        print(f"Welcome, {args.username}!")
        print("1. Create new account")
        print("2. Login to existing account")
        choice = input("Choose an option (1/2): ").strip()

        if choice == "1":
            password = get_password("Create password: ")
            confirm = get_password("Confirm password: ")
            if password != confirm:
                print("Passwords don't match.")
                sys.exit(1)
            payload = {"username": client.username, "password": password}
            message = chat_pb2.ChatMessage(
                type=chat_pb2.MessageType.CREATE_ACCOUNT,
                payload=ParseDict(payload, Struct()),
                sender=client.username,
                recipient="SERVER",
                timestamp=time.time(),
            )
            response = client.stub.CreateAccount(message)
            details = MessageToDict(response.payload).get("text", "")
            print(details)
            # If the response indicates the account exists, prompt for login instead.
            if "already exists" in details.lower():
                print("Account already exists. Please log in instead.")
                password = get_password("Enter password: ")
                if not client.login(password):
                    sys.exit(1)
            else:
                print("Account created successfully. Please log in.")
                password = get_password("Enter password: ")
                if not client.login(password):
                    sys.exit(1)
        elif choice == "2":
            password = get_password("Enter password: ")
            if not client.login(password):
                sys.exit(1)
        else:
            print("Invalid choice")
            sys.exit(1)

        # Start the thread to continuously read incoming messages.
        client.start_read_thread()

        print("\nCommands:")
        print("Send message: <recipient>,<message>")
        print("Delete messages: !delete")
        print("Delete account: !delete_account")
        print("List accounts: !list_accounts")
        print("Press Ctrl+C to quit")

        while True:
            cmd = input().strip()
            if not cmd:
                continue

            if cmd.lower() == "!delete":
                ids_input = input("Enter message IDs to delete (comma-separated): ").strip()
                try:
                    message_ids = [
                        int(x.strip()) for x in ids_input.split(",") if x.strip().isdigit()
                    ]
                    if message_ids:
                        client.delete_messages(message_ids)
                    else:
                        print("No valid message IDs provided.")
                except Exception as e:
                    print(f"Invalid input: {e}")
                continue

            if cmd.lower() == "!delete_account":
                confirm = (
                    input("Are you sure you want to delete your account? (yes/no): ")
                    .strip()
                    .lower()
                )
                if confirm == "yes":
                    client.delete_account()
                    break
                else:
                    print("Account deletion canceled.")
                continue

            if cmd.lower() == "!list_accounts":
                pattern = input("Enter pattern (or press Enter for all): ").strip()
                page = input("Enter page number (default 1): ").strip() or "1"
                try:
                    client.list_accounts(pattern, int(page))
                except Exception as e:
                    print(f"Error listing accounts: {e}")
                continue

            if "," not in cmd:
                print("Invalid format. Use: <recipient>,<message>")
                continue

            recipient, text = cmd.split(",", 1)
            client.send_message(recipient.strip(), text.strip())

    except KeyboardInterrupt:
        print("\nClient interrupted.")
    finally:
        client.close()
