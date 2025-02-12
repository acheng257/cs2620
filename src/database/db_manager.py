import sqlite3
from typing import Any, Dict, List, Optional

import bcrypt


class DatabaseManager:
    def __init__(self, db_path: str = "chat.db") -> None:
        self.db_path: str = db_path
        self.init_database()

    def init_database(self) -> None:
        """Initialize the database with necessary tables."""
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

                # Create messages table with read status
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender TEXT NOT NULL,
                        recipient TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        read BOOLEAN DEFAULT FALSE,
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
        """Create a new account with hashed password."""
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
        """Verify login credentials."""
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
        """Get number of unread messages for a user."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM messages WHERE recipient = ? AND read = FALSE",
                    (username,),
                )
                result = cursor.fetchone()
                return result[0] if result is not None else 0
        except Exception as e:
            print(f"Error getting unread message count: {e}")
            return 0

    def delete_account(self, username: str) -> bool:
        """Delete an account and all associated messages."""
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
        """Check if a user exists."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM accounts WHERE username = ?", (username,))
                return cursor.fetchone() is not None
        except Exception as e:
            print(f"Error checking user existence: {e}")
            return False

    def store_message(self, sender: str, recipient: str, content: str) -> bool:
        """Store a message in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO messages (sender, recipient, content) VALUES (?, ?, ?)",
                    (sender, recipient, content),
                )
                conn.commit()
                return True
        except Exception as e:
            print(f"Error storing message: {e}")
            return False

    def mark_messages_as_read(self, username: str, message_ids: Optional[List[int]] = None) -> bool:
        """Mark messages as read. If no message_ids provided, mark all as read."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if message_ids:
                    # Must build a parameterized query carefully
                    placeholder = ",".join("?" for _ in message_ids)
                    query = f"UPDATE messages SET read = TRUE WHERE recipient = ? \
                        AND id IN ({placeholder})"
                    params = [username] + message_ids
                    cursor.execute(query, params)
                else:
                    cursor.execute(
                        "UPDATE messages SET read = TRUE WHERE recipient = ?",
                        (username,),
                    )
                conn.commit()
                return True
        except Exception as e:
            print(f"Error marking messages as read: {e}")
            return False

    def list_accounts(self, pattern: str = "", page: int = 1, per_page: int = 10) -> Dict[str, Any]:
        """
        Return a dict with keys {users, total, page, per_page}.
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
        Return a dict with keys {messages, total}.
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
                    SELECT id, sender, recipient, content, timestamp, read
                    FROM messages
                    WHERE sender = ? OR recipient = ?
                    ORDER BY timestamp ASC
                    LIMIT ? OFFSET ?
                    """,
                    (username, username, limit, offset),
                )
                rows = cursor.fetchall()

                messages = []
                for row in rows:
                    msg_id, sender, recipient, content, ts, read_status = row
                    messages.append(
                        {
                            "id": msg_id,
                            "from": sender,
                            "to": recipient,
                            "content": content,
                            "timestamp": ts,
                            "is_read": bool(read_status),
                        }
                    )

                return {"messages": messages, "total": total_count}
        except Exception as e:
            print(f"Error getting messages for user: {e}")
            return {"messages": [], "total": 0}

    def delete_messages(self, username: str, message_ids: List[int]) -> bool:
        """
        Delete messages by ID if the user is either the sender or recipient.
        """
        if not message_ids:
            return True
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                placeholders = ",".join("?" for _ in message_ids)
                query = f"""
                    DELETE FROM messages
                    WHERE id IN ({placeholders})
                      AND (sender = ? OR recipient = ?)
                """
                params = list(message_ids) + [username, username]
                cursor.execute(query, params)
                conn.commit()

                # rowcount is the number of rows actually deleted
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting messages: {e}")
            return False

    def get_chat_partners(self, me: str) -> List[str]:
        """
        Return all distinct users who have either
        sent a message to 'me' or received a message from 'me'.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT DISTINCT
                        CASE WHEN sender = ? THEN recipient
                            ELSE sender
                        END AS partner
                    FROM messages
                    WHERE sender = ? OR recipient = ?
                    """,
                    (me, me, me),
                )
                rows = cursor.fetchall()
                partners = [r[0] for r in rows if r[0] != me]
                return partners
        except Exception as e:
            print(f"Error getting chat partners for {me}: {e}")
            return []

    def get_messages_between_users(
        self, user1: str, user2: str, offset: int = 0, limit: int = 999999
    ) -> Dict[str, Any]:
        """
        Return a dict {messages, total} of messages between two users,
        newest first in DB results, then we can reverse if needed.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                query = """
                    SELECT id, sender, recipient, content, timestamp, read
                    FROM messages
                    WHERE (sender = ? AND recipient = ?)
                       OR (sender = ? AND recipient = ?)
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """
                cursor.execute(query, (user1, user2, user2, user1, limit, offset))
                rows = cursor.fetchall()

                messages = []
                for row in rows:
                    msg_id, sender, recipient, content, ts, read_status = row
                    messages.append(
                        {
                            "id": msg_id,
                            "from": sender,
                            "to": recipient,
                            "content": content,
                            "timestamp": ts,
                            "is_read": bool(read_status),
                        }
                    )
                return {"messages": messages, "total": len(messages)}
        except Exception as e:
            print(f"Error in get_messages_between_users pagination: {e}")
            return {"messages": [], "total": 0}
