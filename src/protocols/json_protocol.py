import json

from src.protocols.base import Message, MessageType, Protocol


class JsonProtocol(Protocol):
    """
    JSON protocol implementation for the chat system.

    This protocol serializes messages into JSON format, providing human-readable
    message encoding at the cost of larger message sizes compared to binary format.
    The JSON structure includes all Message fields (type, payload, sender, recipient, timestamp)
    in a standardized format.
    """

    def serialize(self, message: Message) -> bytes:
        """
        Convert a Message object into JSON-encoded bytes.

        Args:
            message (Message): The message to serialize

        Returns:
            bytes: UTF-8 encoded JSON representation of the message

        Note:
            The message type is stored as its integer value for compatibility.
            All fields are included in the JSON structure, even if None.
        """
        data = {
            "type": message.type.value,
            "payload": message.payload,
            "sender": message.sender,
            "recipient": message.recipient,
            "timestamp": message.timestamp,
        }
        return json.dumps(data).encode("utf-8")

    def deserialize(self, data: bytes) -> Message:
        """
        Convert JSON-encoded bytes back into a Message object.

        Args:
            data (bytes): The UTF-8 encoded JSON data to deserialize

        Returns:
            Message: The deserialized Message object

        Raises:
            ValueError: If the JSON data is invalid or missing required fields

        Note:
            Handles missing optional fields (sender, recipient) gracefully.
            Validates message type against the MessageType enum.
        """
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
        """
        Get the name of this protocol implementation.

        Returns:
            str: Always returns "JSON"
        """
        return "JSON"

    def calculate_message_size(self, message: Message) -> int:
        """
        Calculate the size of a message in bytes after JSON serialization.

        Args:
            message (Message): The message to calculate size for

        Returns:
            int: The total number of bytes the message will occupy when serialized

        Note:
            Size includes UTF-8 encoding overhead of the JSON string.
        """
        return len(self.serialize(message))
