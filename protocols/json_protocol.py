import json
from typing import Dict, Any
from protocols.base import Protocol, Message, MessageType

class JsonProtocol(Protocol):
    def serialize(self, message: Message) -> bytes:
        """Serialize a message to JSON format."""
        data = {
            "type": message.type.value,
            "payload": message.payload,
            "sender": message.sender,
            "recipient": message.recipient,
            "timestamp": message.timestamp,
        }
        return json.dumps(data).encode("utf-8")

    def deserialize(self, data: bytes) -> Message:
        """Deserialize JSON data into a Message object."""
        try:
            decoded = json.loads(data.decode("utf-8"))
            return Message(
                type=MessageType(decoded["type"]),
                payload=decoded["payload"],
                sender=decoded.get("sender"),
                recipient=decoded.get("recipient"),
                timestamp=decoded.get("timestamp"),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise ValueError(f"Invalid message format: {str(e)}")

    def get_protocol_name(self) -> str:
        return "JSON"

    def calculate_message_size(self, message: Message) -> int:
        """Calculate the size of a serialized message in bytes."""
        return len(self.serialize(message))
