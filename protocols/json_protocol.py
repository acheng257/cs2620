import json
from protocols.base import Message, MessageType, Protocol
import logging
import time

# Configure logging
logging.basicConfig(
    filename='protocol_performance.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

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
        start_time = time.perf_counter()
        serialized = json.dumps(data).encode('utf-8')
        end_time = time.perf_counter()
        serialization_time = end_time - start_time
        message_size = len(serialized)

        logging.info(f"JSON Serialize Time: {serialization_time:.6f}s, Size: {message_size} bytes")
        return serialized

    def deserialize(self, data: bytes) -> Message:
        """Deserialize JSON data into a Message object."""
        try:
            start_time = time.perf_counter()
            decoded = json.loads(data.decode("utf-8"))
            end_time = time.perf_counter()
            deserialization_time = end_time - start_time
            
            # Log metrics
            logging.info(f"JSON Deserialize Time: {deserialization_time:.6f}s")
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
