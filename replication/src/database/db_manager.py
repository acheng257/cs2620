import sqlite3
import time
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

    The database schema consists of:
    1. accounts: Stores user accounts and password hashes
    2. messages: Stores all messages with metadata and delivery status
    3. chat_preferences: Stores chat-specific preferences (e.g. message_limit)

    All methods include proper error handling and logging.
    """

    def __init__(self, db_path: str = "chat.db") -> None:
        """
        Initialize the database manager.

        Args:
            db_path (str, optional): Path to SQLite database file. Defaults to "chat.db"
        """
        self.db_path: str = db_path
        self._init_db()

    def _init_db(self) -> None:
        """
        Initialize the database schema.

        Creates the necessary tables if they don't exist:
        - accounts: username (PK), password_hash, created_at
        - messages: id (PK), sender, recipient, content, timestamp,
            is_read, is_delivered, sender_deleted, recipient_deleted
        - chat_preferences: username (PK), partner (PK), message_limit

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

                # Create messages table with read, delivered, and deleted status
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
                        sender_deleted BOOLEAN DEFAULT FALSE,
                        recipient_deleted BOOLEAN DEFAULT FALSE,
                        FOREIGN KEY (sender) REFERENCES accounts(username),
                        FOREIGN KEY (recipient) REFERENCES accounts(username)
                    )
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_preferences (
                        username TEXT NOT NULL,
                        partner TEXT NOT NULL,
                        message_limit INTEGER DEFAULT 50,
                        PRIMARY KEY (username, partner),
                        FOREIGN KEY (username) REFERENCES accounts(username),
                        FOREIGN KEY (partner) REFERENCES accounts(username)
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
                    "SELECT COUNT(*) FROM messages WHERE recipient = ?\
                          AND is_read = FALSE AND recipient_deleted = FALSE",
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
            # Check if account exists first
            if not self.user_exists(username):
                return False

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Delete all messages sent by or to the user
                cursor.execute(
                    "DELETE FROM messages WHERE sender = ? OR recipient = ?", (username, username)
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
        self, sender: str, recipient: str, content: str, is_delivered: bool = False
    ) -> Optional[int]:
        """
        Store a new message in the database.

        Args:
            sender (str): Username of message sender
            recipient (str): Username of message recipient
            content (str): Message content
            is_delivered (bool, optional): Whether message was delivered. Defaults to False

        Returns:
            Optional[int]: The message ID if stored successfully, None otherwise

        Note:
            Messages are always stored as unread initially.
            Delivery status can be set for offline message queueing.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO messages (sender, recipient, content, timestamp, is_delivered)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (sender, recipient, content, time.time(), is_delivered),
                )
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            print(f"Error storing message: {e}")
            return None

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
        """
        try:
            if not self.user_exists(username):
                return False

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if message_ids:
                    # Check if any of the messages exist
                    placeholder = ",".join("?" for _ in message_ids)
                    cursor.execute(
                        f"SELECT COUNT(*) FROM messages WHERE id IN ({placeholder})", message_ids
                    )
                    if cursor.fetchone()[0] == 0:
                        return False

                    query = f"UPDATE messages SET is_read = TRUE \
                        WHERE recipient = ? AND id IN ({placeholder})"
                    params = [username] + message_ids
                    cursor.execute(query, params)
                else:
                    cursor.execute(
                        "UPDATE messages SET is_read = TRUE WHERE \
                            recipient = ? AND recipient_deleted = FALSE",
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
            Dict[str, Any]: Dictionary containing:
                'users': List of usernames,
                'total': Total matching accounts,
                'page': Current page number,
                'per_page': Results per page
        """
        try:
            # Return empty results for invalid parameters
            if page < 1 or per_page < 1:
                return {"users": [], "total": 0, "page": page, "per_page": per_page}

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                like_pattern = f"%{pattern}%"

                cursor.execute(
                    "SELECT COUNT(*) FROM accounts WHERE username LIKE ?", (like_pattern,)
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
                print(rows)
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
            Dict[str, Any]: Dictionary containing:
                'messages': List of message dictionaries,
                'total': Total message count
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM messages
                    WHERE (sender = ? OR recipient = ?)
                      AND (sender_deleted = FALSE OR recipient_deleted = FALSE)
                    """,
                    (username, username),
                )
                total_count = cursor.fetchone()[0]

                cursor.execute(
                    """
                    SELECT id, sender, recipient,
                    content, timestamp, is_read,
                      is_delivered, sender_deleted,
                      recipient_deleted
                    FROM messages
                    WHERE (sender = ? AND sender_deleted = FALSE)
                      OR (recipient = ? AND recipient_deleted = FALSE)
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                    """,
                    (username, username, limit, offset),
                )
                rows = cursor.fetchall()
                print(rows)
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
            bool: True if operation completed successfully, False if user doesn't exist
        """
        try:
            # First check if user exists
            if not self.user_exists(username):
                return False

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                for message_id in message_ids:
                    cursor.execute(
                        "SELECT sender, recipient FROM messages WHERE id = ?", (message_id,)
                    )
                    result = cursor.fetchone()
                    if not result:
                        continue
                    sender, recipient = result
                    if username == sender:
                        cursor.execute(
                            "UPDATE messages SET sender_deleted = TRUE WHERE id = ?", (message_id,)
                        )
                    elif username == recipient:
                        cursor.execute(
                            "UPDATE messages SET recipient_deleted = TRUE WHERE id = ?",
                            (message_id,),
                        )
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
        Get messages between two users with pagination.

        Args:
            user1 (str): First username
            user2 (str): Second username
            offset (int, optional): Number of messages to skip. Defaults to 0.
            limit (int, optional): Maximum messages to return. Defaults to 999999.

        Returns:
            Dict[str, Any]: Dictionary containing:
                'messages': List of message dictionaries,
                'total': Total number of messages
        """
        try:
            # Handle negative offset by treating it as 0
            if offset < 0:
                offset = 0
            # Handle negative limit by treating it as 0
            if limit < 0:
                limit = 0

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Mark undelivered messages as delivered
                cursor.execute(
                    "UPDATE messages SET is_delivered = TRUE WHERE sender = \
                        ? AND recipient = ? AND is_delivered = FALSE",
                    (user2, user1),
                )

                query = """
                    SELECT id, sender, recipient, content, timestamp, is_read, is_delivered
                    FROM messages
                    WHERE (
                        (sender = ? AND recipient = ? AND sender_deleted = FALSE)
                        OR
                        (sender = ? AND recipient = ? AND recipient_deleted = FALSE)
                    )
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """
                cursor.execute(query, (user1, user2, user2, user1, limit, offset))
                rows = cursor.fetchall()

                # Count total
                cursor.execute(
                    "SELECT COUNT(*) FROM messages WHERE (sender = ? \
                        AND recipient = ? AND sender_deleted = FALSE) \
                        OR (sender = ? AND recipient = ? AND recipient_deleted = FALSE)",
                    (user1, user2, user1, user2),
                )
                total_count = cursor.fetchone()[0]

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
            print(f"Error in get_messages_between_users: {e}")
            return {"messages": [], "total": 0}

    def get_unread_between_users(self, user1: str, user2: str) -> int:
        """
        Get count of unread messages between two users.

        Args:
            user1 (str): Recipient username
            user2 (str): Sender username

        Returns:
            int: Number of unread messages from user2 to user1
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM messages
                    WHERE recipient = ? AND sender = ? AND is_read = FALSE
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
            List[Dict[str, Any]]: List of undelivered messages
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, sender, content, timestamp
                    FROM messages
                    WHERE recipient = ? AND is_delivered = FALSE AND recipient_deleted = FALSE
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
            message_id (int): ID of the message

        Returns:
            bool: True if message marked as delivered, False otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE messages SET is_delivered = TRUE WHERE id = ?", (message_id,)
                )
                conn.commit()
                return True
        except Exception as e:
            print(f"Error marking message as delivered: {e}")
            return False

    def get_message_limit(self, username: str) -> Any:
        """
        Retrieve the message limit for the given user.

        Args:
            username (str): Username to retrieve the limit for

        Returns:
            int: The message limit. Defaults to 50 if not set or error occurs.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT message_limit FROM user_preferences WHERE username = ?", (username,)
                )
                result = cursor.fetchone()
                if result:
                    return result[0]
                else:
                    # If no record exists, insert default limit (50) and return it.
                    cursor.execute(
                        "INSERT INTO user_preferences (username, message_limit) VALUES (?, ?)",
                        (username, 50),
                    )
                    conn.commit()
                    return 50
        except Exception as e:
            print(f"Error retrieving message limit for user {username}: {e}")
            return 50

    def get_chat_message_limit(self, username: str, partner: str) -> Any:
        """
        Retrieve the message limit for a specific conversation between a user and a partner.
        If no record exists, insert a default limit of 50.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT message_limit FROM chat_preferences WHERE \
                        username = ? AND partner = ?",
                    (username, partner),
                )
                result = cursor.fetchone()
                if result:
                    return result[0]
                else:
                    cursor.execute(
                        "INSERT INTO chat_preferences (username, partner, \
                            message_limit) VALUES (?, ?, ?)",
                        (username, partner, 50),
                    )
                    conn.commit()
                    return 50
        except Exception as e:
            print(f"Error retrieving chat message limit for {username} and {partner}: {e}")
            return 50

    def update_chat_message_limit(self, username: str, partner: str, limit: int) -> bool:
        """
        Update the message limit for a specific conversation.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE chat_preferences SET message_limit = ? \
                        WHERE username = ? AND partner = ?",
                    (limit, username, partner),
                )
                conn.commit()
                return True
        except Exception as e:
            print(f"Error updating chat message limit for {username} and {partner}: {e}")
            return False

    def create_user(self, username: str) -> bool:
        """Create a new user"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (username) VALUES (?)", (username,))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def get_messages(self, username: str) -> List[Dict]:
        """Get all messages for a user"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, sender, recipient, content, timestamp, is_delivered
                    FROM messages
                    WHERE recipient = ?
                    ORDER BY timestamp DESC
                    """,
                    (username,),
                )
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Error retrieving messages: {e}")
            return []

    def delete_message(self, message_id: int) -> bool:
        """Delete a message from the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"Error deleting message: {e}")
            return False

    def get_undelivered_messages(self, recipient: str) -> List[Dict]:
        """Get all undelivered messages for a user"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, sender, recipient, content, timestamp, is_delivered
                    FROM messages
                    WHERE recipient = ? AND is_delivered = 0
                    ORDER BY timestamp ASC
                    """,
                    (recipient,),
                )
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Error retrieving undelivered messages: {e}")
            return []
