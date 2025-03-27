gRPC Client Module
================

.. automodule:: src.chat_grpc_client
   :members:
   :undoc-members:
   :show-inheritance:

This module provides the client implementation for the replicated chat system. Key features include:

- Automatic leader discovery
- Seamless server failover
- Background message reading
- Real-time message delivery
- Chat history retrieval
- Account management
- Message status tracking

The client maintains background threads for:

1. Reading incoming messages
2. Monitoring leader status
3. Automatic reconnection on failure 