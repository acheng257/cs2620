import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class MessageType(Enum):
    """
    Enumeration of all possible message types in the chat system.

    Attributes:
        CREATE_ACCOUNT (0): Request to create a new user account
        LOGIN (1): Request to log in to an existing account
        LIST_ACCOUNTS (2): Request to list available user accounts
        SEND_MESSAGE (3): Request to send a message to another user
        READ_MESSAGES (4): Request to read messages from a conversation
        DELETE_MESSAGES (5): Request to delete specific messages
        DELETE_ACCOUNT (6): Request to delete a user account
        ERROR (7): Error response from server
        SUCCESS (8): Success response from server
        LIST_CHAT_PARTNERS (9): Request to list users with active conversations
    """

    CREATE_ACCOUNT = 0
    LOGIN = 1
    LIST_ACCOUNTS = 2
    SEND_MESSAGE = 3
    READ_MESSAGES = 4
    DELETE_MESSAGES = 5
    DELETE_ACCOUNT = 6
    ERROR = 7
    SUCCESS = 8
    LIST_CHAT_PARTNERS = 9


# TODO(@ItamarRocha): need to make sure it should be optional
@dataclass
class Message:
    """
    Represents a message in the chat system.

    Attributes:
        type (MessageType): The type of message (e.g., LOGIN, SEND_MESSAGE)
        payload (Dict[str, Any]): Message content and metadata
        sender (Optional[str]): Username of the message sender
        recipient (Optional[str]): Username of the message recipient
        timestamp (float): Unix timestamp of when the message was created
    """

    type: MessageType
    payload: Dict[str, Any]
    sender: Optional[str]
    recipient: Optional[str]
    timestamp: float = time.time()


# Abstract class Protocol that will be used by the other protocols
class Protocol(ABC):
    """
    Abstract base class for chat protocol implementations.

    This class defines the interface that all protocol implementations must follow.
    Concrete implementations (JSON, Binary) must provide their own serialization
    and deserialization logic.
    """

    @abstractmethod
    def serialize(self, message: Message) -> bytes:
        """
        Convert a Message object into bytes for transmission.

        Args:
            message (Message): The message to serialize

        Returns:
            bytes: The serialized message ready for transmission
        """
        pass

    @abstractmethod
    def deserialize(self, data: bytes) -> Message:
        """
        Convert received bytes back into a Message object.

        Args:
            data (bytes): The received bytes to deserialize

        Returns:
            Message: The deserialized Message object
        """
        pass

    @abstractmethod
    def get_protocol_name(self) -> str:
        """
        Get the name of this protocol implementation.

        Returns:
            str: The protocol name (e.g., "JSON", "Binary")
        """
        pass

    @abstractmethod
    def calculate_message_size(self, message: Message) -> int:
        """
        Calculate the size in bytes of a message after serialization.

        Args:
            message (Message): The message to calculate size for

        Returns:
            int: The size in bytes of the serialized message
        """
        pass
