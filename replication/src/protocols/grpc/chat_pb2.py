# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# NO CHECKED-IN PROTOBUF GENCODE
# source: src/protocols/grpc/chat.proto
# Protobuf Python Version: 5.29.0
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import runtime_version as _runtime_version
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC,
    5,
    29,
    0,
    '',
    'src/protocols/grpc/chat.proto'
)
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()


from google.protobuf import struct_pb2 as google_dot_protobuf_dot_struct__pb2


DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x1dsrc/protocols/grpc/chat.proto\x12\x04\x63hat\x1a\x1cgoogle/protobuf/struct.proto\"\x8e\x01\n\x0b\x43hatMessage\x12\x1f\n\x04type\x18\x01 \x01(\x0e\x32\x11.chat.MessageType\x12(\n\x07payload\x18\x02 \x01(\x0b\x32\x17.google.protobuf.Struct\x12\x0e\n\x06sender\x18\x03 \x01(\t\x12\x11\n\trecipient\x18\x04 \x01(\t\x12\x11\n\ttimestamp\x18\x05 \x01(\x01\"\xea\x02\n\x12ReplicationMessage\x12#\n\x04type\x18\x01 \x01(\x0e\x32\x15.chat.ReplicationType\x12\x0c\n\x04term\x18\x02 \x01(\x05\x12\x11\n\tserver_id\x18\x03 \x01(\t\x12)\n\x0cvote_request\x18\x04 \x01(\x0b\x32\x11.chat.VoteRequestH\x00\x12+\n\rvote_response\x18\x05 \x01(\x0b\x32\x12.chat.VoteResponseH\x00\x12\x37\n\x13message_replication\x18\x06 \x01(\x0b\x32\x18.chat.MessageReplicationH\x00\x12\x39\n\x14replication_response\x18\x07 \x01(\x0b\x32\x19.chat.ReplicationResponseH\x00\x12$\n\theartbeat\x18\x08 \x01(\x0b\x32\x0f.chat.HeartbeatH\x00\x12\x11\n\ttimestamp\x18\t \x01(\x01\x42\t\n\x07\x63ontent\"<\n\x0bVoteRequest\x12\x15\n\rlast_log_term\x18\x01 \x01(\x05\x12\x16\n\x0elast_log_index\x18\x02 \x01(\x05\"$\n\x0cVoteResponse\x12\x14\n\x0cvote_granted\x18\x01 \x01(\x08\"\\\n\x12MessageReplication\x12\x12\n\nmessage_id\x18\x01 \x01(\x05\x12\x0e\n\x06sender\x18\x02 \x01(\t\x12\x11\n\trecipient\x18\x03 \x01(\t\x12\x0f\n\x07\x63ontent\x18\x04 \x01(\t\":\n\x13ReplicationResponse\x12\x0f\n\x07success\x18\x01 \x01(\x08\x12\x12\n\nmessage_id\x18\x02 \x01(\x05\"!\n\tHeartbeat\x12\x14\n\x0c\x63ommit_index\x18\x01 \x01(\x05*\xbd\x01\n\x0bMessageType\x12\x12\n\x0e\x43REATE_ACCOUNT\x10\x00\x12\t\n\x05LOGIN\x10\x01\x12\x11\n\rLIST_ACCOUNTS\x10\x02\x12\x10\n\x0cSEND_MESSAGE\x10\x03\x12\x11\n\rREAD_MESSAGES\x10\x04\x12\x13\n\x0f\x44\x45LETE_MESSAGES\x10\x05\x12\x12\n\x0e\x44\x45LETE_ACCOUNT\x10\x06\x12\t\n\x05\x45RROR\x10\x07\x12\x0b\n\x07SUCCESS\x10\x08\x12\x16\n\x12LIST_CHAT_PARTNERS\x10\t*\xa6\x01\n\x0fReplicationType\x12\r\n\tHEARTBEAT\x10\x00\x12\x10\n\x0cREQUEST_VOTE\x10\x01\x12\x15\n\x11REPLICATE_MESSAGE\x10\x02\x12\x11\n\rVOTE_RESPONSE\x10\x03\x12\x18\n\x14REPLICATION_RESPONSE\x10\x04\x12\x17\n\x13REPLICATION_SUCCESS\x10\x05\x12\x15\n\x11REPLICATION_ERROR\x10\x06\x32\xd5\x04\n\nChatServer\x12\x37\n\rCreateAccount\x12\x11.chat.ChatMessage\x1a\x11.chat.ChatMessage\"\x00\x12/\n\x05Login\x12\x11.chat.ChatMessage\x1a\x11.chat.ChatMessage\"\x00\x12\x35\n\x0bSendMessage\x12\x11.chat.ChatMessage\x1a\x11.chat.ChatMessage\"\x00\x12\x38\n\x0cReadMessages\x12\x11.chat.ChatMessage\x1a\x11.chat.ChatMessage\"\x00\x30\x01\x12\x38\n\x0e\x44\x65leteMessages\x12\x11.chat.ChatMessage\x1a\x11.chat.ChatMessage\"\x00\x12\x37\n\rDeleteAccount\x12\x11.chat.ChatMessage\x1a\x11.chat.ChatMessage\"\x00\x12\x36\n\x0cListAccounts\x12\x11.chat.ChatMessage\x1a\x11.chat.ChatMessage\"\x00\x12:\n\x10ListChatPartners\x12\x11.chat.ChatMessage\x1a\x11.chat.ChatMessage\"\x00\x12:\n\x10ReadConversation\x12\x11.chat.ChatMessage\x1a\x11.chat.ChatMessage\"\x00\x12I\n\x11HandleReplication\x12\x18.chat.ReplicationMessage\x1a\x18.chat.ReplicationMessage\"\x00\x62\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'src.protocols.grpc.chat_pb2', _globals)
if not _descriptor._USE_C_DESCRIPTORS:
  DESCRIPTOR._loaded_options = None
  _globals['_MESSAGETYPE']._serialized_start=869
  _globals['_MESSAGETYPE']._serialized_end=1058
  _globals['_REPLICATIONTYPE']._serialized_start=1061
  _globals['_REPLICATIONTYPE']._serialized_end=1227
  _globals['_CHATMESSAGE']._serialized_start=70
  _globals['_CHATMESSAGE']._serialized_end=212
  _globals['_REPLICATIONMESSAGE']._serialized_start=215
  _globals['_REPLICATIONMESSAGE']._serialized_end=577
  _globals['_VOTEREQUEST']._serialized_start=579
  _globals['_VOTEREQUEST']._serialized_end=639
  _globals['_VOTERESPONSE']._serialized_start=641
  _globals['_VOTERESPONSE']._serialized_end=677
  _globals['_MESSAGEREPLICATION']._serialized_start=679
  _globals['_MESSAGEREPLICATION']._serialized_end=771
  _globals['_REPLICATIONRESPONSE']._serialized_start=773
  _globals['_REPLICATIONRESPONSE']._serialized_end=831
  _globals['_HEARTBEAT']._serialized_start=833
  _globals['_HEARTBEAT']._serialized_end=866
  _globals['_CHATSERVER']._serialized_start=1230
  _globals['_CHATSERVER']._serialized_end=1827
# @@protoc_insertion_point(module_scope)
