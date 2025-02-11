from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum
import time


class MessageType(Enum):
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
    payload: Any
    sender: str
    recipient: str
    timestamp: float = time.time()


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
