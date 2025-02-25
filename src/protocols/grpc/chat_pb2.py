# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# NO CHECKED-IN PROTOBUF GENCODE
# source: chat.proto
# Protobuf Python Version: 5.29.0
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import runtime_version as _runtime_version
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
# from google.protobuf import struct_pb2 as google_dot_protobuf_dot_struct__pb2

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 5, 29, 0, "", "chat.proto"
)
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\nchat.proto\x12\x04\x63hat\x1a\x1cgoogle/protobuf/struct.proto"\x8e\x01\n\x0b\x43hat\
        Message\\x12\x1f\n\x04type\x18\x01 \x01(\x0e\x32\x11.chat.MessageType\x12(\n\x07pay\
            load\x18\x02 \x01(\x0b\x32\x17.google.protobuf.Struct\x12\x0e\n\x06sender\x18\x03\
                  \x01(\t\x12\x11\n\trecipient\x18\x04 \x01(\t\x12\x11\n\ttimestamp\x18\x05\
                    \x01(\x01*\xbd\x01\n\x0bMessageType\x12\x12\n\x0e\x43REATE_ACCOUNT\x10\x00\
                    \x12\t\n\x05LOGIN\x10\x01\x12\x11\n\rLIST_ACCOUNTS\x10\x02\x12\x10\n\x0c\
                    SEND_MESSAGE\x10\x03\x12\x11\n\rREAD_MESSAGES\x10\x04\x12\x13\n\x0f\x44\x45\
                        LETE_MESSAGES\x10\x05\x12\x12\n\x0e\x44\x45LETE_ACCOUNT\x10\x06\x12\t\n\
                            \x05\x45RROR\x10\x07\x12\x0b\n\x07SUCCESS\x10\x08\x12\x16\n\x12\
                            LIST_CHAT_PARTNERS\x10\t2\xbf\x03\n\x0b\x43hatService\x12\x33\n\x0b\
                                SendMessage\x12\x11.chat.ChatMessage\x1a\x11.chat.ChatMessage\
                                    \x12\x36\n\x0cReadMessages\x12\x11.chat.ChatMessage\x1a\x11.\
                                    chat.ChatMessage0\x01\x12\x35\n\rCreateAccount\x12\x11.chat.\
                                        ChatMessage\x1a\x11.chat.ChatMessage\x12-\n\x05Login\
                                            \x12\x11.chat.ChatMessage\x1a\x11.chat.ChatMessage\
                                            \x12\x34\n\x0cListAccounts\x12\x11.chat.ChatMessage\
                                            \x1a\x11.chat.ChatMessage\x12\x36\n\x0e\x44\x65lete\
                                            Messages\x12\x11.chat.ChatMessage\x1a\x11.chat.Chat\
                                                Message\x12\x35\n\rDeleteAccount\x12\x11.chat.\
                                                    ChatMessage\x1a\x11.chat.ChatMessage\
                                                        \x12\x38\n\x10ListChatPartners\x12\
                                                        \x11.chat.ChatMessage\x1a\x11.chat.\
                                                        ChatMessageb\x06proto3'
)

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "chat_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_MESSAGETYPE"]._serialized_start = 196
    _globals["_MESSAGETYPE"]._serialized_end = 385
    _globals["_CHATMESSAGE"]._serialized_start = 51
    _globals["_CHATMESSAGE"]._serialized_end = 193
    _globals["_CHATSERVICE"]._serialized_start = 388
    _globals["_CHATSERVICE"]._serialized_end = 835
# @@protoc_insertion_point(module_scope)
