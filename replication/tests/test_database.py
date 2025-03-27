import os
from pathlib import Path
from typing import Generator

import pytest

from src.database.db_manager import DatabaseManager


@pytest.fixture
def db_manager() -> Generator[DatabaseManager, None, None]:
    """Create a test database manager that uses a temporary database file."""
    test_db_path = "test_chat.db"
    manager = DatabaseManager(db_path=test_db_path)
    yield manager
    # Cleanup: remove test database file if it exists.
    if os.path.exists(test_db_path):
        os.remove(test_db_path)


def test_create_account(db_manager: DatabaseManager) -> None:
    """Test account creation functionality."""
    assert db_manager.create_account("testuser", "password123")
    # Duplicate creation should fail.
    assert not db_manager.create_account("testuser", "different_password")
    assert db_manager.user_exists("testuser")
    assert not db_manager.user_exists("nonexistent")


def test_verify_login(db_manager: DatabaseManager) -> None:
    """Test login verification functionality."""
    db_manager.create_account("logintest", "password123")
    assert db_manager.verify_login("logintest", "password123")
    assert not db_manager.verify_login("logintest", "wrongpassword")
    assert not db_manager.verify_login("nonexistent", "password123")


def test_delete_account(db_manager: DatabaseManager) -> None:
    """Test account deletion functionality."""
    db_manager.create_account("user1", "password123")
    db_manager.create_account("user2", "password123")
    db_manager.store_message("user1", "user2", "Hello!")
    db_manager.store_message("user2", "user1", "Hi back!")
    assert db_manager.delete_account("user1")
    assert not db_manager.user_exists("user1")
    messages = db_manager.get_messages_between_users("user1", "user2")
    assert len(messages["messages"]) == 0


def test_messaging(db_manager: DatabaseManager) -> None:
    """Test message storage and retrieval functionality."""
    db_manager.create_account("sender", "password123")
    db_manager.create_account("recipient", "password123")
    msg_id = db_manager.store_message("sender", "recipient", "Test message")
    assert msg_id is not None
    messages = db_manager.get_messages_between_users("sender", "recipient")
    assert len(messages["messages"]) == 1
    assert messages["messages"][0]["content"] == "Test message"
    assert not messages["messages"][0]["is_read"]
    assert db_manager.mark_messages_as_read("recipient", [msg_id])
    messages = db_manager.get_messages_between_users("sender", "recipient")
    assert messages["messages"][0]["is_read"]


def test_message_deletion(db_manager: DatabaseManager) -> None:
    """Test message deletion functionality."""
    db_manager.create_account("user1", "password123")
    db_manager.create_account("user2", "password123")
    msg_id1 = db_manager.store_message("user1", "user2", "Message 1")
    msg_id2 = db_manager.store_message("user1", "user2", "Message 2")
    assert msg_id1 is not None and msg_id2 is not None
    assert db_manager.delete_messages("user2", [msg_id1])
    messages = db_manager.get_messages_between_users("user2", "user1")
    assert len(messages["messages"]) == 1
    assert messages["messages"][0]["id"] == msg_id2


def test_chat_partners(db_manager: DatabaseManager) -> None:
    """Test chat partner listing functionality."""
    db_manager.create_account("user1", "password123")
    db_manager.create_account("user2", "password123")
    db_manager.create_account("user3", "password123")
    db_manager.store_message("user1", "user2", "Hello user2!")
    db_manager.store_message("user2", "user1", "Hi user1!")
    db_manager.store_message("user1", "user3", "Hello user3!")
    partners = db_manager.get_chat_partners("user1")
    assert len(partners) == 2
    assert "user2" in partners and "user3" in partners


def test_message_delivery(db_manager: DatabaseManager) -> None:
    """Test message delivery status functionality."""
    db_manager.create_account("sender", "password123")
    db_manager.create_account("recipient", "password123")
    msg_id = db_manager.store_message("sender", "recipient", "Test message", is_delivered=False)
    assert msg_id is not None
    undelivered = db_manager.get_undelivered_messages("recipient")
    assert len(undelivered) == 1
    assert db_manager.mark_message_as_delivered(msg_id)
    undelivered = db_manager.get_undelivered_messages("recipient")
    assert len(undelivered) == 0


def test_pagination(db_manager: DatabaseManager) -> None:
    """Test pagination functionality for messages and account listing."""
    db_manager.create_account("user1", "password123")
    db_manager.create_account("user2", "password123")
    for i in range(15):
        db_manager.store_message("user1", "user2", f"Message {i}")
    messages = db_manager.get_messages_between_users("user1", "user2", limit=10)
    assert len(messages["messages"]) == 10
    assert messages["total"] == 15
    messages = db_manager.get_messages_between_users("user1", "user2", offset=10, limit=10)
    assert len(messages["messages"]) == 5
    assert messages["total"] == 15


def test_account_listing(db_manager: DatabaseManager) -> None:
    """Test account listing and pattern matching functionality."""
    db_manager.create_account("test1", "password123")
    db_manager.create_account("test2", "password123")
    db_manager.create_account("other", "password123")
    accounts = db_manager.list_accounts(pattern="test")
    assert len(accounts["users"]) == 2
    assert all(acc.startswith("test") for acc in accounts["users"])
    accounts = db_manager.list_accounts()
    assert len(accounts["users"]) == 3


def test_message_status_operations(db_manager: DatabaseManager) -> None:
    """Test message status operations in detail."""
    db_manager.create_account("sender", "pass")
    db_manager.create_account("receiver", "pass")
    msg_id = db_manager.store_message("sender", "receiver", "test", is_delivered=False)
    assert msg_id is not None
    undelivered = db_manager.get_undelivered_messages("receiver")
    assert len(undelivered) == 1 and undelivered[0]["content"] == "test"
    assert db_manager.mark_message_as_delivered(msg_id)
    undelivered = db_manager.get_undelivered_messages("receiver")
    assert len(undelivered) == 0
    assert db_manager.get_unread_between_users("receiver", "sender") == 1
    db_manager.mark_messages_as_read("receiver", [msg_id])
    assert db_manager.get_unread_between_users("receiver", "sender") == 0


def test_pagination_edge_cases(db_manager: DatabaseManager) -> None:
    """Test pagination with various edge cases."""
    db_manager.create_account("user1", "pass")
    db_manager.create_account("user2", "pass")
    messages = db_manager.get_messages_between_users("user1", "user2", offset=0, limit=10)
    assert len(messages["messages"]) == 0 and messages["total"] == 0
    msg_ids = []
    for i in range(5):
        msg_id = db_manager.store_message("user1", "user2", f"Message {i}")
        assert msg_id is not None
        msg_ids.append(msg_id)
    messages = db_manager.get_messages_between_users("user1", "user2", offset=10, limit=10)
    assert len(messages["messages"]) == 0 and messages["total"] == 5
    messages = db_manager.get_messages_between_users("user1", "user2", offset=-1, limit=10)
    assert len(messages["messages"]) == 5 and messages["total"] == 5


def test_account_listing_edge_cases(db_manager: DatabaseManager) -> None:
    """Test account listing with various patterns and edge cases."""
    db_manager.create_account("test1", "pass")
    db_manager.create_account("test2", "pass")
    db_manager.create_account("other", "pass")
    accounts = db_manager.list_accounts("")
    assert len(accounts["users"]) == 3
    accounts = db_manager.list_accounts("nonexistent")
    assert len(accounts["users"]) == 0
    accounts = db_manager.list_accounts(per_page=1)
    assert len(accounts["users"]) == 1 and accounts["total"] == 3


def test_chat_partners_edge_cases(db_manager: DatabaseManager) -> None:
    """Test chat partner functionality with edge cases."""
    db_manager.create_account("user1", "pass")
    db_manager.create_account("user2", "pass")
    db_manager.create_account("user3", "pass")
    partners = db_manager.get_chat_partners("user1")
    assert len(partners) == 0
    msg_id = db_manager.store_message("user1", "user2", "Hello")
    assert msg_id is not None
    assert len(db_manager.get_chat_partners("user1")) == 1
    db_manager.delete_messages("user1", [msg_id])
    assert len(db_manager.get_chat_partners("user1")) == 1
    msg_id2 = db_manager.store_message("user2", "user1", "Hi back")
    partners = db_manager.get_chat_partners("user1")
    assert len(partners) == 1 and "user2" in partners


def test_unread_message_count(db_manager: DatabaseManager) -> None:
    """Test unread message count functionality."""
    db_manager.create_account("user1", "pass")
    db_manager.create_account("user2", "pass")
    db_manager.create_account("user3", "pass")
    assert db_manager.get_unread_message_count("user1") == 0
    msg_id1 = db_manager.store_message("user2", "user1", "Hello")
    assert msg_id1 is not None
    assert db_manager.get_unread_message_count("user1") == 1
    msg_id2 = db_manager.store_message("user3", "user1", "Hi")
    assert msg_id2 is not None
    assert db_manager.get_unread_message_count("user1") == 2
    db_manager.mark_messages_as_read("user1", [msg_id1])
    assert db_manager.get_unread_message_count("user1") == 1
    db_manager.delete_messages("user1", [msg_id2])
    assert db_manager.get_unread_message_count("user1") == 0
    assert db_manager.get_unread_message_count("nonexistent") == 0


def test_messages_for_user(db_manager: DatabaseManager) -> None:
    """Test message retrieval for a user."""
    db_manager.create_account("user1", "pass")
    db_manager.create_account("user2", "pass")
    messages = db_manager.get_messages_for_user("user1")
    assert len(messages["messages"]) == 0 and messages["total"] == 0
    msg_id1 = db_manager.store_message("user1", "user2", "Message 1")
    msg_id2 = db_manager.store_message("user2", "user1", "Message 2")
    msg_id3 = db_manager.store_message("user1", "user2", "Message 3")
    assert msg_id1 and msg_id2 and msg_id3
    messages = db_manager.get_messages_for_user("user1", limit=2)
    assert len(messages["messages"]) == 2 and messages["total"] == 3
    messages = db_manager.get_messages_for_user("user1", offset=2, limit=2)
    assert len(messages["messages"]) == 1
    db_manager.delete_messages("user1", [msg_id1])
    messages = db_manager.get_messages_for_user("user1")
    assert len(messages["messages"]) == 2
    messages = db_manager.get_messages_for_user("nonexistent")
    assert len(messages["messages"]) == 0 and messages["total"] == 0


def test_get_message_limit(db_manager: DatabaseManager) -> None:
    """Test retrieving message limit for a user."""
    db_manager.create_account("test_user", "pass")
    limit = db_manager.get_message_limit("test_user")
    assert limit == 50
    limit = db_manager.get_message_limit("nonexistent")
    assert limit == 50


def test_get_chat_message_limit(db_manager: DatabaseManager) -> None:
    """Test retrieving message limit for a specific chat."""
    db_manager.create_account("user1", "pass")
    db_manager.create_account("user2", "pass")
    limit = db_manager.get_chat_message_limit("user1", "user2")
    assert limit == 50
    limit = db_manager.get_chat_message_limit("nonexistent1", "nonexistent2")
    assert limit == 50


def test_message_limit_database_error(db_manager: DatabaseManager) -> None:
    """Test message limit handling with database errors."""
    db_manager.create_account("test_user", "pass")
    original_path = db_manager.db_path
    db_manager.db_path = "nonexistent/path/chat.db"
    limit = db_manager.get_message_limit("test_user")
    assert limit == 50
    limit = db_manager.get_chat_message_limit("test_user", "partner")
    assert limit == 50
    success = db_manager.update_chat_message_limit("test_user", "partner", 100)
    assert not success
    db_manager.db_path = original_path
