import json
import struct
import logging
import time

# Configure logging
logging.basicConfig(
    filename='protocol_performance.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

from protocols.base import Message, MessageType, Protocol


class BinaryProtocol(Protocol):
    # Message format:
    # [1 byte: message type][4 bytes: payload length][N bytes: payload]
    # [1 byte: sender length][N bytes: sender][1 bytes: recipient length][N bytes: recipient]
    # [8 bytes: timestamp (double)]
    def serialize(self, message: Message) -> bytes:
        start_time = time.perf_counter()
        message_type = message.type.value
        payload_bytes = json.dumps(message.payload).encode("utf-8")
        sender_bytes = message.sender.encode("utf-8") if message.sender else b""
        recipient_bytes = message.recipient.encode("utf-8") if message.recipient else b""

        header = struct.pack("!BL", message_type, len(payload_bytes))
        sender_header = struct.pack("!B", len(sender_bytes))
        recipient_header = struct.pack("!B", len(recipient_bytes))
        timestamp = struct.pack("!d", message.timestamp or 0.0)
        serialized = header + payload_bytes + sender_header + sender_bytes + recipient_header + recipient_bytes + timestamp

        end_time = time.perf_counter()
        serialization_time = end_time - start_time
        message_size = len(serialized)
        
        # Log metrics
        logging.info(f"Binary Serialize Time: {serialization_time:.6f}s, Size: {message_size} bytes")

        return serialized

    def deserialize(self, data: bytes) -> Message:
        try:
            start_time = time.perf_counter()
            offset = 0
            message_type, payload_length = struct.unpack_from("!BL", data, offset)
            offset += 5  # message type and payload length take 5 bytes in total

            payload = data[offset : offset + payload_length].decode("utf-8")
            offset += payload_length

            sender_length = struct.unpack_from("!B", data, offset)[0]  # unpack_from returns a tuple
            offset += 1
            sender = (
                data[offset : offset + sender_length].decode("utf-8") if sender_length > 0 else None
            )
            offset += sender_length

            recipient_length = struct.unpack_from("!B", data, offset)[0]
            offset += 1
            recipient = (
                data[offset : offset + recipient_length].decode("utf-8")
                if recipient_length > 0
                else None
            )
            offset += recipient_length

            timestamp = struct.unpack_from("!d", data, offset)[0]
            end_time = time.perf_counter()
            deserialization_time = end_time - start_time
            
            # Log metrics
            logging.info(f"Binary Deserialize Time: {deserialization_time:.6f}s")

            return Message(
                type=MessageType(message_type),
                payload=json.loads(payload),
                sender=sender,
                recipient=recipient,
                timestamp=timestamp,
            )
        except (struct.error, json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Invalid binary message format: {str(e)}")

    def get_protocol_name(self) -> str:
        return "Binary"

    def calculate_message_size(self, message: Message) -> int:
        return len(self.serialize(message))
