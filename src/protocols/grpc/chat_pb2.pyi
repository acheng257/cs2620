from typing import ClassVar as _ClassVar
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

DESCRIPTOR: _descriptor.FileDescriptor

class MessageType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CREATE_ACCOUNT: _ClassVar[MessageType]
    LOGIN: _ClassVar[MessageType]
    LIST_ACCOUNTS: _ClassVar[MessageType]
    SEND_MESSAGE: _ClassVar[MessageType]
    READ_MESSAGES: _ClassVar[MessageType]
    DELETE_MESSAGES: _ClassVar[MessageType]
    DELETE_ACCOUNT: _ClassVar[MessageType]
    ERROR: _ClassVar[MessageType]
    SUCCESS: _ClassVar[MessageType]
    LIST_CHAT_PARTNERS: _ClassVar[MessageType]

CREATE_ACCOUNT: MessageType
LOGIN: MessageType
LIST_ACCOUNTS: MessageType
SEND_MESSAGE: MessageType
READ_MESSAGES: MessageType
DELETE_MESSAGES: MessageType
DELETE_ACCOUNT: MessageType
ERROR: MessageType
SUCCESS: MessageType
LIST_CHAT_PARTNERS: MessageType

class ChatMessage(_message.Message):
    __slots__ = ("type", "payload", "sender", "recipient", "timestamp")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    SENDER_FIELD_NUMBER: _ClassVar[int]
    RECIPIENT_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    type: MessageType
    payload: _struct_pb2.Struct
    sender: str
    recipient: str
    timestamp: float
    def __init__(
        self,
        type: _Optional[_Union[MessageType, str]] = ...,
        payload: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...,
        sender: _Optional[str] = ...,
        recipient: _Optional[str] = ...,
        timestamp: _Optional[float] = ...,
    ) -> None: ...
