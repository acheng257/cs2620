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
    # Cleanup: close connections and remove test database
    del manager
    if os.path.exists(test_db_path):
        os.remove(test_db_path)


def test_create_account(db_manager: DatabaseManager) -> None:
    """Test account creation functionality."""
    # Test successful account creation
    assert db_manager.create_account("testuser", "password123")

    # Test duplicate username
    assert not db_manager.create_account("testuser", "different_password")

    # Test user existence
    assert db_manager.user_exists("testuser")
    assert not db_manager.user_exists("nonexistent")


def test_verify_login(db_manager: DatabaseManager) -> None:
    """Test login verification functionality."""
    # Create test account
    db_manager.create_account("logintest", "password123")

    # Test successful login
    assert db_manager.verify_login("logintest", "password123")

    # Test wrong password
    assert not db_manager.verify_login("logintest", "wrongpassword")

    # Test nonexistent user
    assert not db_manager.verify_login("nonexistent", "password123")


def test_delete_account(db_manager: DatabaseManager) -> None:
    """Test account deletion functionality."""
    # Create test account and messages
    db_manager.create_account("user1", "password123")
    db_manager.create_account("user2", "password123")

    # Store some messages
    db_manager.store_message("user1", "user2", "Hello!")
    db_manager.store_message("user2", "user1", "Hi back!")

    # Delete account
    assert db_manager.delete_account("user1")

    # Verify account and messages are gone
    assert not db_manager.user_exists("user1")
    messages = db_manager.get_messages_between_users("user1", "user2")
    assert len(messages["messages"]) == 0


def test_messaging(db_manager: DatabaseManager) -> None:
    """Test message storage and retrieval functionality."""
    # Create test accounts
    db_manager.create_account("sender", "password123")
    db_manager.create_account("recipient", "password123")

    # Test message storage
    msg_id = db_manager.store_message("sender", "recipient", "Test message")
    assert msg_id is not None, "Message storage should succeed"

    # Test message retrieval
    messages = db_manager.get_messages_between_users("sender", "recipient")
    assert len(messages["messages"]) == 1
    assert messages["messages"][0]["content"] == "Test message"
    assert not messages["messages"][0]["is_read"]

    # Test marking messages as read
    assert db_manager.mark_messages_as_read("recipient", [msg_id])
    messages = db_manager.get_messages_between_users("sender", "recipient")
    assert messages["messages"][0]["is_read"]


def test_message_deletion(db_manager: DatabaseManager) -> None:
    """Test message deletion functionality."""
    # Create test accounts and messages
    db_manager.create_account("user1", "password123")
    db_manager.create_account("user2", "password123")

    msg_id1 = db_manager.store_message("user1", "user2", "Message 1")
    msg_id2 = db_manager.store_message("user1", "user2", "Message 2")
    assert msg_id1 is not None and msg_id2 is not None, "Message storage should succeed"

    # Test deleting specific messages for recipient
    assert db_manager.delete_messages("user2", [msg_id1])
    messages = db_manager.get_messages_between_users("user2", "user1")
    assert len(messages["messages"]) == 1
    assert messages["messages"][0]["id"] == msg_id2


def test_chat_partners(db_manager: DatabaseManager) -> None:
    """Test chat partner listing functionality."""
    # Create test accounts
    db_manager.create_account("user1", "password123")
    db_manager.create_account("user2", "password123")
    db_manager.create_account("user3", "password123")

    # Create some conversations
    db_manager.store_message("user1", "user2", "Hello user2!")
    db_manager.store_message("user2", "user1", "Hi user1!")
    db_manager.store_message("user1", "user3", "Hello user3!")

    # Test chat partner listing
    partners = db_manager.get_chat_partners("user1")
    assert len(partners) == 2
    assert "user2" in partners
    assert "user3" in partners


def test_message_delivery(db_manager: DatabaseManager) -> None:
    """Test message delivery status functionality."""
    # Create test accounts
    db_manager.create_account("sender", "password123")
    db_manager.create_account("recipient", "password123")

    # Test undelivered message
    msg_id = db_manager.store_message("sender", "recipient", "Test message", is_delivered=False)
    assert msg_id is not None, "Message storage should succeed"

    # Check undelivered messages
    undelivered = db_manager.get_undelivered_messages("recipient")
    assert len(undelivered) == 1

    # Mark as delivered
    assert db_manager.mark_message_as_delivered(msg_id)
    undelivered = db_manager.get_undelivered_messages("recipient")
    assert len(undelivered) == 0


def test_pagination(db_manager: DatabaseManager) -> None:
    """Test pagination functionality for messages and account listing."""
    # Create test accounts
    db_manager.create_account("user1", "password123")
    db_manager.create_account("user2", "password123")

    # Create multiple messages
    for i in range(15):
        db_manager.store_message("user1", "user2", f"Message {i}")

    # Test message pagination
    messages = db_manager.get_messages_between_users("user1", "user2", limit=10)
    assert len(messages["messages"]) == 10
    assert messages["total"] == 15

    messages = db_manager.get_messages_between_users("user1", "user2", offset=10, limit=10)
    assert len(messages["messages"]) == 5
    assert messages["total"] == 15


def test_account_listing(db_manager: DatabaseManager) -> None:
    """Test account listing and pattern matching functionality."""
    # Create test accounts
    db_manager.create_account("test1", "password123")
    db_manager.create_account("test2", "password123")
    db_manager.create_account("other", "password123")

    # Test pattern matching
    accounts = db_manager.list_accounts(pattern="test")
    assert len(accounts["users"]) == 2
    assert all(acc.startswith("test") for acc in accounts["users"])

    # Test no pattern
    accounts = db_manager.list_accounts()
    assert len(accounts["users"]) == 3


def test_message_status_operations(db_manager: DatabaseManager) -> None:
    """Test message status operations in detail."""
    # Setup test accounts and messages
    db_manager.create_account("sender", "pass")
    db_manager.create_account("receiver", "pass")

    # Test undelivered messages
    msg_id = db_manager.store_message("sender", "receiver", "test", is_delivered=False)
    assert msg_id is not None, "Message storage should succeed"

    undelivered = db_manager.get_undelivered_messages("receiver")
    assert len(undelivered) == 1
    assert undelivered[0]["content"] == "test"

    # Test marking as delivered
    assert db_manager.mark_message_as_delivered(msg_id)
    undelivered = db_manager.get_undelivered_messages("receiver")
    assert len(undelivered) == 0

    # Test unread count between users
    assert db_manager.get_unread_between_users("receiver", "sender") == 1
    db_manager.mark_messages_as_read("receiver", [msg_id])
    assert db_manager.get_unread_between_users("receiver", "sender") == 0


def test_pagination_edge_cases(db_manager: DatabaseManager) -> None:
    """Test pagination with various edge cases."""
    # Setup test accounts
    db_manager.create_account("user1", "pass")
    db_manager.create_account("user2", "pass")

    # Test empty results
    messages = db_manager.get_messages_between_users("user1", "user2", offset=0, limit=10)
    assert len(messages["messages"]) == 0
    assert messages["total"] == 0

    # Test with offset beyond available messages
    msg_ids = []
    for i in range(5):
        msg_id = db_manager.store_message("user1", "user2", f"Message {i}")
        assert msg_id is not None, "Message storage should succeed"
        msg_ids.append(msg_id)

    messages = db_manager.get_messages_between_users("user1", "user2", offset=10, limit=10)
    assert len(messages["messages"]) == 0
    assert messages["total"] == 5

    # Test with negative offset (should handle gracefully)
    messages = db_manager.get_messages_between_users("user1", "user2", offset=-1, limit=10)
    assert len(messages["messages"]) == 5
    assert messages["total"] == 5


def test_account_listing_edge_cases(db_manager: DatabaseManager) -> None:
    """Test account listing with various patterns and edge cases."""
    # Setup test accounts
    db_manager.create_account("test1", "pass")
    db_manager.create_account("test2", "pass")
    db_manager.create_account("other", "pass")

    # Test with empty pattern
    accounts = db_manager.list_accounts("")
    assert len(accounts["users"]) == 3

    # Test with non-matching pattern
    accounts = db_manager.list_accounts("nonexistent")
    assert len(accounts["users"]) == 0

    # Test pagination
    accounts = db_manager.list_accounts(per_page=1)
    print(accounts)
    assert len(accounts["users"]) == 1
    assert accounts["total"] == 3


def test_chat_partners_edge_cases(db_manager: DatabaseManager) -> None:
    """Test chat partner functionality with edge cases."""
    # Setup test accounts
    db_manager.create_account("user1", "pass")
    db_manager.create_account("user2", "pass")
    db_manager.create_account("user3", "pass")

    # Test with no messages
    partners = db_manager.get_chat_partners("user1")
    assert len(partners) == 0

    # Test with deleted messages
    msg_id = db_manager.store_message("user1", "user2", "Hello")
    assert msg_id is not None, "Message storage should succeed"
    assert len(db_manager.get_chat_partners("user1")) == 1

    db_manager.delete_messages("user1", [msg_id])
    # Partner should still appear as recipient hasn't deleted the message
    assert len(db_manager.get_chat_partners("user1")) == 1

    # Test with messages in both directions
    msg_id2 = db_manager.store_message("user2", "user1", "Hi back")
    assert msg_id2 is not None, "Message storage should succeed"
    partners = db_manager.get_chat_partners("user1")
    assert len(partners) == 1
    assert "user2" in partners


def test_message_deletion_edge_cases(db_manager: DatabaseManager) -> None:
    """Test message deletion with various edge cases."""
    # Setup test accounts and messages
    db_manager.create_account("user1", "pass")
    db_manager.create_account("user2", "pass")

    # Test deleting non-existent message
    assert db_manager.delete_messages("user1", [999])

    # Test deleting message as non-participant
    msg_id = db_manager.store_message("user1", "user2", "Hello")
    assert msg_id is not None, "Message storage should succeed"
    assert not db_manager.delete_messages("nonexistent", [msg_id])

    # Test deleting same message multiple times
    assert db_manager.delete_messages("user1", [msg_id])
    assert db_manager.delete_messages("user1", [msg_id])  # Should succeed but have no effect

    # Verify message is still visible to recipient
    messages = db_manager.get_messages_between_users("user2", "user1")
    assert len(messages["messages"]) == 1


def test_unread_message_count(db_manager: DatabaseManager) -> None:
    """Test unread message count functionality."""
    # Setup test accounts
    db_manager.create_account("user1", "pass")
    db_manager.create_account("user2", "pass")
    db_manager.create_account("user3", "pass")

    # Test with no messages
    assert db_manager.get_unread_message_count("user1") == 0

    # Test with one unread message
    msg_id1 = db_manager.store_message("user2", "user1", "Hello")
    assert msg_id1 is not None, "Message storage should succeed"
    assert db_manager.get_unread_message_count("user1") == 1

    # Test with multiple unread messages from different users
    msg_id2 = db_manager.store_message("user3", "user1", "Hi")
    assert msg_id2 is not None, "Message storage should succeed"
    assert db_manager.get_unread_message_count("user1") == 2

    # Test after marking one message as read
    db_manager.mark_messages_as_read("user1", [msg_id1])
    assert db_manager.get_unread_message_count("user1") == 1

    # Test with deleted messages
    db_manager.delete_messages("user1", [msg_id2])
    assert db_manager.get_unread_message_count("user1") == 0

    # Test with non-existent user
    assert db_manager.get_unread_message_count("nonexistent") == 0


def test_messages_for_user(db_manager: DatabaseManager) -> None:
    """Test message retrieval for a user."""
    # Setup test accounts
    db_manager.create_account("user1", "pass")
    db_manager.create_account("user2", "pass")

    # Test with no messages
    messages = db_manager.get_messages_for_user("user1")
    assert len(messages["messages"]) == 0
    assert messages["total"] == 0

    # Add some messages
    msg_id1 = db_manager.store_message("user1", "user2", "Message 1")
    msg_id2 = db_manager.store_message("user2", "user1", "Message 2")
    msg_id3 = db_manager.store_message("user1", "user2", "Message 3")
    assert (
        msg_id1 is not None and msg_id2 is not None and msg_id3 is not None
    ), "Message storage should succeed"

    # Test message retrieval with pagination
    messages = db_manager.get_messages_for_user("user1", limit=2)
    assert len(messages["messages"]) == 2
    assert messages["total"] == 3  # Total should be all messages

    # Test offset
    messages = db_manager.get_messages_for_user("user1", offset=2, limit=2)
    assert len(messages["messages"]) == 1  # Should get remaining message

    # Test after deleting a message
    db_manager.delete_messages("user1", [msg_id1])
    messages = db_manager.get_messages_for_user("user1")
    assert len(messages["messages"]) == 2

    # Test with non-existent user
    messages = db_manager.get_messages_for_user("nonexistent")
    assert len(messages["messages"]) == 0
    assert messages["total"] == 0


def test_database_initialization_error(tmp_path: Path) -> None:
    """Test database initialization error handling."""
    # Try to create database in a non-existent directory
    invalid_path = tmp_path / "nonexistent" / "chat.db"
    with pytest.raises(Exception):
        DatabaseManager(db_path=str(invalid_path))

    # Try to create database with invalid permissions
    # Note: This test might not work on all systems due to permission handling
    read_only_path = tmp_path / "readonly.db"
    read_only_path.touch(mode=0o444)  # Create read-only file
    with pytest.raises(Exception):
        DatabaseManager(db_path=str(read_only_path))


def test_get_message_limit(db_manager: DatabaseManager) -> None:
    """Test retrieving message limit for a user."""
    # Create test account
    db_manager.create_account("test_user", "pass")

    # Test default limit for new user
    limit = db_manager.get_message_limit("test_user")
    assert limit == 50

    # Test nonexistent user
    limit = db_manager.get_message_limit("nonexistent")
    assert limit == 50


def test_get_chat_message_limit(db_manager: DatabaseManager) -> None:
    """Test retrieving message limit for a specific chat."""
    # Create test accounts
    db_manager.create_account("user1", "pass")
    db_manager.create_account("user2", "pass")

    # Test default limit for new chat
    limit = db_manager.get_chat_message_limit("user1", "user2")
    assert limit == 50

    # Test nonexistent users
    limit = db_manager.get_chat_message_limit("nonexistent1", "nonexistent2")
    assert limit == 50


def test_message_limit_database_error(db_manager: DatabaseManager) -> None:
    """Test message limit handling with database errors."""
    # Create test account
    db_manager.create_account("test_user", "pass")

    # Corrupt database path temporarily
    original_path = db_manager.db_path
    db_manager.db_path = "nonexistent/path/chat.db"

    # Test error handling in get_message_limit
    limit = db_manager.get_message_limit("test_user")
    assert limit == 50  # Should return default value

    # Test error handling in get_chat_message_limit
    limit = db_manager.get_chat_message_limit("test_user", "partner")
    assert limit == 50  # Should return default value

    # Test error handling in update_chat_message_limit
    success = db_manager.update_chat_message_limit("test_user", "partner", 100)
    assert not success  # Should return False on error

    # Restore database path
    db_manager.db_path = original_path
