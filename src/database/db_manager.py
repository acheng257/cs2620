# db_manager.py
import sqlite3
from typing import Any, Dict, List, Optional

import bcrypt


class DatabaseManager:
    """
    Manages all database operations for the chat system.

    This class handles:
    - User account management (creation, verification, deletion)
    - Message storage and retrieval
    - Message status tracking (read/unread, delivered/undelivered)
    - Chat partner relationships
    - Message history and pagination

    The database schema consists of two main tables:
    1. accounts: Stores user accounts and password hashes
    2. messages: Stores all messages with metadata and delivery status

    All methods include proper error handling and logging.
    """

    def __init__(self, db_path: str = "chat.db") -> None:
        """
        Initialize the database manager.

        Args:
            db_path (str, optional): Path to SQLite database file. Defaults to "chat.db"
        """
        self.db_path: str = db_path
        self.init_database()

    def init_database(self) -> None:
        """
        Initialize the database schema.

        Creates the necessary tables if they don't exist:
        - accounts: username (PK), password_hash, created_at
        - messages: id (PK), sender, recipient, content, timestamp, is_read, is_delivered

        Raises:
            Exception: If database initialization fails
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Create accounts table
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS accounts (
                        username TEXT PRIMARY KEY,
                        password_hash BLOB NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """
                )

                # Create messages table with read and delivered status
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender TEXT NOT NULL,
                        recipient TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        is_read BOOLEAN DEFAULT FALSE,
                        is_delivered BOOLEAN DEFAULT TRUE,
                        FOREIGN KEY (sender) REFERENCES accounts(username),
                        FOREIGN KEY (recipient) REFERENCES accounts(username)
                    )
                """
                )

                conn.commit()
        except Exception as e:
            print(f"Error initializing database: {e}")
            raise

    def create_account(self, username: str, password: str) -> bool:
        """
        Create a new user account.

        Args:
            username (str): Desired username
            password (str): User's password

        Returns:
            bool: True if account created successfully, False if username exists or error occurs

        Note:
            Password is hashed using bcrypt before storage.
            Username must be unique.
        """
        try:
            salt = bcrypt.gensalt()
            password_hash = bcrypt.hashpw(password.encode("utf-8"), salt)

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO accounts (username, password_hash) VALUES (?, ?)",
                    (username, password_hash),
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            # Username already exists
            return False
        except Exception as e:
            print(f"Error creating account: {e}")
            return False

    def verify_login(self, username: str, password: str) -> bool:
        """
        Verify user login credentials.

        Args:
            username (str): Username to verify
            password (str): Password to verify

        Returns:
            bool: True if credentials are valid, False otherwise

        Note:
            Uses bcrypt to verify password against stored hash.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT password_hash FROM accounts WHERE username = ?", (username,))
                result = cursor.fetchone()

                if result is None:
                    return False

                stored_hash = result[0]
                return bool(bcrypt.checkpw(password.encode("utf-8"), stored_hash))
        except Exception as e:
            print(f"Error verifying login: {e}")
            return False

    def get_unread_message_count(self, username: str) -> int:
        """
        Get total number of unread messages for a user.

        Args:
            username (str): Username to check

        Returns:
            int: Number of unread messages across all conversations

        Note:
            Only counts messages where user is the recipient.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM messages WHERE recipient = ? AND is_read = FALSE",
                    (username,),
                )
                result = cursor.fetchone()
                return result[0] if result is not None else 0
        except Exception as e:
            print(f"Error getting unread message count: {e}")
            return 0

    def delete_account(self, username: str) -> bool:
        """
        Delete a user account and all associated messages.

        Args:
            username (str): Username of account to delete

        Returns:
            bool: True if account deleted successfully, False otherwise

        Note:
            This operation cascades to delete all messages sent by or to the user.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Delete all messages sent by or to the user
                cursor.execute(
                    "DELETE FROM messages WHERE sender = ? OR recipient = ?",
                    (username, username),
                )
                # Delete the account
                cursor.execute("DELETE FROM accounts WHERE username = ?", (username,))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error deleting account: {e}")
            return False

    def user_exists(self, username: str) -> bool:
        """
        Check if a username exists in the database.

        Args:
            username (str): Username to check

        Returns:
            bool: True if user exists, False otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM accounts WHERE username = ?", (username,))
                return cursor.fetchone() is not None
        except Exception as e:
            print(f"Error checking user existence: {e}")
            return False

    def store_message(
        self, sender: str, recipient: str, content: str, is_delivered: bool = True
    ) -> bool:
        """
        Store a new message in the database.

        Args:
            sender (str): Username of message sender
            recipient (str): Username of message recipient
            content (str): Message content
            is_delivered (bool, optional): Whether message was delivered. Defaults to True

        Returns:
            bool: True if message stored successfully, False otherwise

        Note:
            Messages are always stored as unread initially.
            Delivery status can be set for offline message queueing.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO messages (sender, recipient, content, is_delivered, \
                        is_read) VALUES (?, ?, ?, ?, ?)",
                    (sender, recipient, content, is_delivered, False),
                )
                conn.commit()
                return True
        except Exception as e:
            print(f"Error storing message: {e}")
            return False

    def mark_messages_as_read(self, username: str, message_ids: Optional[List[int]] = None) -> bool:
        """
        Mark messages as read for a user.

        Args:
            username (str): Username of message recipient
            message_ids (Optional[List[int]], optional): Specific message IDs to mark.
                If None, marks all messages as read. Defaults to None.

        Returns:
            bool: True if operation successful, False otherwise

        Note:
            Only marks messages where user is the recipient.
            Can mark specific messages or all messages as read.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if message_ids:
                    # Must build a parameterized query carefully
                    placeholder = ",".join("?" for _ in message_ids)
                    query = f"UPDATE messages SET is_read = TRUE WHERE \
                        recipient = ? AND id IN ({placeholder})"
                    params = [username] + message_ids
                    cursor.execute(query, params)
                else:
                    cursor.execute(
                        "UPDATE messages SET is_read = TRUE WHERE recipient = ?",
                        (username,),
                    )
                conn.commit()
                return True
        except Exception as e:
            print(f"Error marking messages as read: {e}")
            return False

    def list_accounts(self, pattern: str = "", page: int = 1, per_page: int = 10) -> Dict[str, Any]:
        """
        List user accounts with optional pattern matching and pagination.

        Args:
            pattern (str, optional): Username pattern to filter by. Defaults to "".
            page (int, optional): Page number (1-based). Defaults to 1.
            per_page (int, optional): Results per page. Defaults to 10.

        Returns:
            Dict[str, Any]: {
                'users': List of usernames,
                'total': Total matching accounts,
                'page': Current page number,
                'per_page': Results per page
            }

        Note:
            Pattern matching is case-sensitive and uses SQL LIKE with wildcards.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                like_pattern = f"%{pattern}%"

                # Count total
                cursor.execute(
                    "SELECT COUNT(*) FROM accounts WHERE username LIKE ?",
                    (like_pattern,),
                )
                total_count = cursor.fetchone()[0]

                offset = (page - 1) * per_page

                cursor.execute(
                    """
                    SELECT username FROM accounts
                    WHERE username LIKE ?
                    ORDER BY username
                    LIMIT ? OFFSET ?
                    """,
                    (like_pattern, per_page, offset),
                )
                rows = cursor.fetchall()

                return {
                    "users": [r[0] for r in rows],
                    "total": total_count,
                    "page": page,
                    "per_page": per_page,
                }
        except Exception as e:
            print(f"Error listing accounts: {e}")
            return {"users": [], "total": 0, "page": page, "per_page": per_page}

    def get_messages_for_user(
        self, username: str, offset: int = 0, limit: int = 10
    ) -> Dict[str, Any]:
        """
        Get all messages for a user with pagination.

        Args:
            username (str): Username to get messages for
            offset (int, optional): Number of messages to skip. Defaults to 0.
            limit (int, optional): Maximum messages to return. Defaults to 10.

        Returns:
            Dict[str, Any]: {
                'messages': List of message dictionaries,
                'total': Total message count
            }

            Each message dictionary contains:
            - id: Message ID
            - from: Sender username
            - to: Recipient username
            - content: Message content
            - timestamp: Message timestamp
            - is_read: Read status
            - is_delivered: Delivery status

        Note:
            Includes both sent and received messages.
            Messages are ordered by timestamp (newest first).
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Count total
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM messages
                    WHERE sender = ? OR recipient = ?
                    """,
                    (username, username),
                )
                total_count = cursor.fetchone()[0]

                cursor.execute(
                    """
                    SELECT id, sender, recipient, content, timestamp, is_read, is_delivered
                    FROM messages
                    WHERE sender = ? OR recipient = ?
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                    """,
                    (username, username, limit, offset),
                )
                rows = cursor.fetchall()

                messages = []
                for row in rows:
                    messages.append(
                        {
                            "id": row[0],
                            "from": row[1],
                            "to": row[2],
                            "content": row[3],
                            "timestamp": row[4],
                            "is_read": bool(row[5]),
                            "is_delivered": bool(row[6]),
                        }
                    )

                return {"messages": messages, "total": total_count}
        except Exception as e:
            print(f"Error getting messages: {e}")
            return {"messages": [], "total": 0}

    def delete_messages(self, username: str, message_ids: List[int]) -> bool:
        """
        Delete specific messages for a user.

        Args:
            username (str): Username of message owner
            message_ids (List[int]): List of message IDs to delete

        Returns:
            bool: True if all messages deleted successfully, False otherwise

        Note:
            Only deletes messages where the user is either sender or recipient.
            Operation is atomic - either all messages are deleted or none are.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Build parameterized query
                placeholder = ",".join("?" for _ in message_ids)
                query = f"""
                    DELETE FROM messages
                    WHERE id IN ({placeholder})
                    AND (sender = ? OR recipient = ?)
                """
                params = message_ids + [username, username]
                cursor.execute(query, params)
                conn.commit()
                return True
        except Exception as e:
            print(f"Error deleting messages: {e}")
            return False

    def get_chat_partners(self, me: str) -> List[str]:
        """
        Get list of users that have exchanged messages with the specified user.

        Args:
            me (str): Username to find chat partners for

        Returns:
            List[str]: List of usernames that have exchanged messages with the user

        Note:
            Includes both users that have sent messages to or received messages from
            the specified user. Results are unique and sorted alphabetically.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT DISTINCT
                        CASE
                            WHEN sender = ? THEN recipient
                            ELSE sender
                        END as partner
                    FROM messages
                    WHERE sender = ? OR recipient = ?
                    ORDER BY partner
                    """,
                    (me, me, me),
                )
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error getting chat partners: {e}")
            return []

    def get_messages_between_users(
        self, user1: str, user2: str, offset: int = 0, limit: int = 999999
    ) -> Dict[str, Any]:
        """
        Get messages exchanged between two specific users.

        Args:
            user1 (str): First username
            user2 (str): Second username
            offset (int, optional): Number of messages to skip. Defaults to 0
            limit (int, optional): Maximum messages to return. Defaults to 999999

        Returns:
            Dict[str, Any]: {
                'messages': List of message dictionaries,
                'total': Total message count
            }

            Each message dictionary contains:
            - id: Message ID
            - from: Sender username
            - to: Recipient username
            - content: Message content
            - timestamp: Message timestamp
            - is_read: Read status
            - is_delivered: Delivery status

        Note:
            Messages are ordered by timestamp (newest first).
            Includes messages in both directions between the users.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get total count first
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM messages
                    WHERE (sender = ? AND recipient = ?)
                    OR (sender = ? AND recipient = ?)
                    """,
                    (user1, user2, user2, user1),
                )
                total_count = cursor.fetchone()[0]

                # Then get the actual messages
                cursor.execute(
                    """
                    SELECT id, sender, recipient, content, timestamp, is_read, is_delivered
                    FROM messages
                    WHERE (sender = ? AND recipient = ?)
                    OR (sender = ? AND recipient = ?)
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                    """,
                    (user1, user2, user2, user1, limit, offset),
                )

                messages = []
                for row in cursor.fetchall():
                    messages.append(
                        {
                            "id": row[0],
                            "from": row[1],
                            "to": row[2],
                            "content": row[3],
                            "timestamp": row[4],
                            "is_read": bool(row[5]),
                            "is_delivered": bool(row[6]),
                        }
                    )

                return {"messages": messages, "total": total_count}
        except Exception as e:
            print(f"Error getting messages between users: {e}")
            return {"messages": [], "total": 0}

    def get_unread_between_users(self, user1: str, user2: str) -> int:
        """
        Get count of unread messages between two users.

        Args:
            user1 (str): Username of message recipient
            user2 (str): Username of message sender

        Returns:
            int: Number of unread messages from user2 to user1

        Note:
            Only counts messages where user1 is recipient and user2 is sender.
            Does not count messages in the opposite direction.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM messages
                    WHERE recipient = ?
                    AND sender = ?
                    AND is_read = FALSE
                    """,
                    (user1, user2),
                )
                result = cursor.fetchone()
                return result[0] if result is not None else 0
        except Exception as e:
            print(f"Error getting unread count between users: {e}")
            return 0

    def get_undelivered_messages(self, username: str) -> List[Dict[str, Any]]:
        """
        Get all undelivered messages for a user.

        Args:
            username (str): Username to get undelivered messages for

        Returns:
            List[Dict[str, Any]]: List of undelivered messages, each containing:
                - id: Message ID
                - from: Sender username
                - content: Message content
                - timestamp: Message timestamp

        Note:
            Only retrieves messages where the user is the recipient.
            Messages are ordered by timestamp (oldest first).
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, sender, content, timestamp
                    FROM messages
                    WHERE recipient = ? AND is_delivered = FALSE
                    ORDER BY timestamp ASC
                    """,
                    (username,),
                )
                messages = []
                for row in cursor.fetchall():
                    messages.append(
                        {
                            "id": row[0],
                            "from": row[1],
                            "content": row[2],
                            "timestamp": row[3],
                        }
                    )
                return messages
        except Exception as e:
            print(f"Error getting undelivered messages: {e}")
            return []

    def mark_message_as_delivered(self, message_id: int) -> bool:
        """
        Mark a specific message as delivered.

        Args:
            message_id (int): ID of the message to mark as delivered

        Returns:
            bool: True if message marked as delivered, False if error occurs

        Note:
            Used when a queued message is successfully delivered to an online user.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE messages SET is_delivered = TRUE WHERE id = ?",
                    (message_id,),
                )
                conn.commit()
                return True
        except Exception as e:
            print(f"Error marking message as delivered: {e}")
            return False

    def get_last_message_id(self, sender: str, recipient: str) -> Optional[int]:
        """
        Get the ID of the most recent message between two users.

        Args:
            sender (str): Username of message sender
            recipient (str): Username of message recipient

        Returns:
            Optional[int]: ID of the most recent message, or None if no messages exist

        Note:
            Only looks for messages in the specified direction (sender to recipient).
            Does not consider messages in the opposite direction.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id
                    FROM messages
                    WHERE sender = ? AND recipient = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (sender, recipient),
                )
                result = cursor.fetchone()
                return result[0] if result is not None else None
        except Exception as e:
            print(f"Error getting last message ID: {e}")
            return None
