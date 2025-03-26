src.protocols.grpc package
========================

Protocol Buffer Definitions
---------------------------

The gRPC protocol is defined using Protocol Buffers in the ``chat.proto`` file. This defines the message types and service interfaces used for communication.

Generated Code
-------------

.. automodule:: src.protocols.grpc.chat_pb2
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: src.protocols.grpc.chat_pb2_grpc
   :members:
   :undoc-members:
   :show-inheritance:

Message Types
------------

The protocol defines the following message types:

- ``ChatMessage``: The main message type used for all communication
- ``MessageType``: Enum defining different types of messages (CREATE_ACCOUNT, LOGIN, etc.)

Service Definition
------------------

The ``ChatServer`` service provides the following RPC methods:

- ``SendMessage``: Send a message to another user
- ``ReadMessages``: Stream messages to a client
- ``CreateAccount``: Create a new user account
- ``Login``: Authenticate a user
- ``ListAccounts``: List user accounts
- ``DeleteMessages``: Delete specified messages
- ``DeleteAccount``: Delete a user account
- ``ListChatPartners``: List chat partners
- ``ReadConversation``: Read conversation history 