from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum


class MessageType(Enum):
    # CREATE_ACCOUNT = "create_account"
    # LOGIN = "login"
    # LIST_ACCOUNTS = "list_accounts"
    # SEND_MESSAGE = "send_message"
    # READ_MESSAGES = "read_messages"
    # DELETE_MESSAGES = "delete_messages"
    # DELETE_ACCOUNT = "delete_account"
    # ERROR = "error"
    # SUCCESS = "success"
    CREATE_ACCOUNT = 0
    LOGIN = 1
    LIST_ACCOUNTS = 2
    SEND_MESSAGE = 3
    READ_MESSAGES = 4
    DELETE_MESSAGES = 5
    DELETE_ACCOUNT = 6
    ERROR = 7
    SUCCESS = 8


@dataclass
class Message:
    type: MessageType
    payload: Dict[str, Any]
    sender: Optional[str] = None
    recipient: Optional[str] = None
    timestamp: Optional[float] = None


# Abstract class Protocol that will be used by the other protocols
class Protocol(ABC):
    @abstractmethod
    def serialize(self, message: Message) -> bytes:
        """Serialize a message to bytes for transmission."""
        pass

    @abstractmethod
    def deserialize(self, data: bytes) -> Message:
        """Deserialize received bytes into a Message object."""
        pass

    @abstractmethod
    def get_protocol_name(self) -> str:
        """Return the name of the protocol implementation."""
        pass

    @abstractmethod
    def calculate_message_size(self, message: Message) -> int:
        """Calculate the size of a serialized message in bytes."""
        pass
