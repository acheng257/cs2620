from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

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
    GET_LEADER: _ClassVar[MessageType]

class ReplicationType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    HEARTBEAT: _ClassVar[ReplicationType]
    REQUEST_VOTE: _ClassVar[ReplicationType]
    REPLICATE_MESSAGE: _ClassVar[ReplicationType]
    VOTE_RESPONSE: _ClassVar[ReplicationType]
    REPLICATION_RESPONSE: _ClassVar[ReplicationType]
    REPLICATION_SUCCESS: _ClassVar[ReplicationType]
    REPLICATION_ERROR: _ClassVar[ReplicationType]
    REPLICATE_ACCOUNT: _ClassVar[ReplicationType]
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
GET_LEADER: MessageType
HEARTBEAT: ReplicationType
REQUEST_VOTE: ReplicationType
REPLICATE_MESSAGE: ReplicationType
VOTE_RESPONSE: ReplicationType
REPLICATION_RESPONSE: ReplicationType
REPLICATION_SUCCESS: ReplicationType
REPLICATION_ERROR: ReplicationType
REPLICATE_ACCOUNT: ReplicationType

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
    def __init__(self, type: _Optional[_Union[MessageType, str]] = ..., payload: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., sender: _Optional[str] = ..., recipient: _Optional[str] = ..., timestamp: _Optional[float] = ...) -> None: ...

class ReplicationMessage(_message.Message):
    __slots__ = ("type", "term", "server_id", "vote_request", "vote_response", "message_replication", "replication_response", "heartbeat", "account_replication", "timestamp")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TERM_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    VOTE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    VOTE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_REPLICATION_FIELD_NUMBER: _ClassVar[int]
    REPLICATION_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    HEARTBEAT_FIELD_NUMBER: _ClassVar[int]
    ACCOUNT_REPLICATION_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    type: ReplicationType
    term: int
    server_id: str
    vote_request: VoteRequest
    vote_response: VoteResponse
    message_replication: MessageReplication
    replication_response: ReplicationResponse
    heartbeat: Heartbeat
    account_replication: AccountReplication
    timestamp: float
    def __init__(self, type: _Optional[_Union[ReplicationType, str]] = ..., term: _Optional[int] = ..., server_id: _Optional[str] = ..., vote_request: _Optional[_Union[VoteRequest, _Mapping]] = ..., vote_response: _Optional[_Union[VoteResponse, _Mapping]] = ..., message_replication: _Optional[_Union[MessageReplication, _Mapping]] = ..., replication_response: _Optional[_Union[ReplicationResponse, _Mapping]] = ..., heartbeat: _Optional[_Union[Heartbeat, _Mapping]] = ..., account_replication: _Optional[_Union[AccountReplication, _Mapping]] = ..., timestamp: _Optional[float] = ...) -> None: ...

class VoteRequest(_message.Message):
    __slots__ = ("last_log_term", "last_log_index")
    LAST_LOG_TERM_FIELD_NUMBER: _ClassVar[int]
    LAST_LOG_INDEX_FIELD_NUMBER: _ClassVar[int]
    last_log_term: int
    last_log_index: int
    def __init__(self, last_log_term: _Optional[int] = ..., last_log_index: _Optional[int] = ...) -> None: ...

class VoteResponse(_message.Message):
    __slots__ = ("vote_granted",)
    VOTE_GRANTED_FIELD_NUMBER: _ClassVar[int]
    vote_granted: bool
    def __init__(self, vote_granted: bool = ...) -> None: ...

class MessageReplication(_message.Message):
    __slots__ = ("message_id", "sender", "recipient", "content")
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    SENDER_FIELD_NUMBER: _ClassVar[int]
    RECIPIENT_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    message_id: int
    sender: str
    recipient: str
    content: str
    def __init__(self, message_id: _Optional[int] = ..., sender: _Optional[str] = ..., recipient: _Optional[str] = ..., content: _Optional[str] = ...) -> None: ...

class ReplicationResponse(_message.Message):
    __slots__ = ("success", "message_id")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message_id: int
    def __init__(self, success: bool = ..., message_id: _Optional[int] = ...) -> None: ...

class Heartbeat(_message.Message):
    __slots__ = ("commit_index",)
    COMMIT_INDEX_FIELD_NUMBER: _ClassVar[int]
    commit_index: int
    def __init__(self, commit_index: _Optional[int] = ...) -> None: ...

class AccountReplication(_message.Message):
    __slots__ = ("username",)
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    username: str
    def __init__(self, username: _Optional[str] = ...) -> None: ...
