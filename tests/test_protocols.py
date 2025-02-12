from typing import List

import pytest

from protocols.base import Message, MessageType
from protocols.binary_protocol import BinaryProtocol
from protocols.json_protocol import JsonProtocol


@pytest.fixture
def json_protocol() -> JsonProtocol:
    return JsonProtocol()


@pytest.fixture
def binary_protocol() -> BinaryProtocol:
    return BinaryProtocol()


@pytest.fixture
def sample_messages() -> List[Message]:
    return [
        Message(
            type=MessageType.CREATE_ACCOUNT,
            payload={"username": "test_user", "password": "hashed_password"},
            sender=None,
            recipient=None,
        ),
        Message(
            type=MessageType.SEND_MESSAGE,
            payload={"content": "Hello, World!"},
            sender="alice",
            recipient="bob",
        ),
        Message(
            type=MessageType.LIST_ACCOUNTS,
            payload={"pattern": "*"},
            sender="alice",
            recipient=None,
        ),
        Message(
            type=MessageType.READ_MESSAGES,
            payload={"count": 5},
            sender="bob",
            recipient=None,
        ),
    ]


class TestJsonProtocol:
    def test_serialize_deserialize(
        self, json_protocol: JsonProtocol, sample_messages: List[Message]
    ) -> None:
        """Test that messages can be serialized and deserialized correctly using JSON protocol."""
        for original_msg in sample_messages:
            serialized = json_protocol.serialize(original_msg)
            deserialized = json_protocol.deserialize(serialized)

            assert deserialized.type == original_msg.type
            assert deserialized.payload == original_msg.payload
            assert deserialized.sender == original_msg.sender
            assert deserialized.recipient == original_msg.recipient
            assert isinstance(deserialized.timestamp, float)

    def test_invalid_json(self, json_protocol: JsonProtocol) -> None:
        """Test handling of invalid JSON data."""
        with pytest.raises(ValueError):
            json_protocol.deserialize(b"invalid json data")

    def test_protocol_name(self, json_protocol: JsonProtocol) -> None:
        """Test protocol name is correct."""
        assert json_protocol.get_protocol_name() == "JSON"

    def test_message_size(
        self, json_protocol: JsonProtocol, sample_messages: List[Message]
    ) -> None:
        """Test message size calculation."""
        for msg in sample_messages:
            size = json_protocol.calculate_message_size(msg)
            assert size > 0
            assert size == len(json_protocol.serialize(msg))


class TestBinaryProtocol:
    def test_serialize_deserialize(
        self, binary_protocol: BinaryProtocol, sample_messages: List[Message]
    ) -> None:
        """Test that messages can be serialized and deserialized correctly using Binary protocol."""
        for original_msg in sample_messages:
            serialized = binary_protocol.serialize(original_msg)
            deserialized = binary_protocol.deserialize(serialized)

            assert deserialized.type == original_msg.type
            assert deserialized.payload == original_msg.payload
            assert deserialized.sender == original_msg.sender
            assert deserialized.recipient == original_msg.recipient
            assert isinstance(deserialized.timestamp, float)

    def test_invalid_binary_data(self, binary_protocol: BinaryProtocol) -> None:
        """Test handling of invalid binary data."""
        with pytest.raises(ValueError):
            binary_protocol.deserialize(b"invalid binary data")

    def test_protocol_name(self, binary_protocol: BinaryProtocol) -> None:
        """Test protocol name is correct."""
        assert binary_protocol.get_protocol_name() == "Binary"

    def test_message_size(
        self, binary_protocol: BinaryProtocol, sample_messages: List[Message]
    ) -> None:
        """Test message size calculation."""
        for msg in sample_messages:
            size = binary_protocol.calculate_message_size(msg)
            assert size > 0
            assert size == len(binary_protocol.serialize(msg))

    def test_empty_sender_recipient(self, binary_protocol: BinaryProtocol) -> None:
        """Test handling of messages with empty sender/recipient."""
        msg = Message(
            type=MessageType.ERROR,
            payload={"error": "test error"},
            sender=None,
            recipient=None,
        )
        serialized = binary_protocol.serialize(msg)
        deserialized = binary_protocol.deserialize(serialized)

        assert deserialized.sender is None
        assert deserialized.recipient is None


def test_protocol_comparison(
    json_protocol: JsonProtocol, binary_protocol: BinaryProtocol, sample_messages: List[Message]
) -> None:
    """Compare sizes between JSON and Binary protocols."""
    for msg in sample_messages:
        json_size = json_protocol.calculate_message_size(msg)
        binary_size = binary_protocol.calculate_message_size(msg)

        # This is not a strict test, just informative
        print(f"\nMessage type: {msg.type}")
        print(f"JSON size: {json_size} bytes")
        print(f"Binary size: {binary_size} bytes")
        print(f"Difference: {json_size - binary_size} bytes")
