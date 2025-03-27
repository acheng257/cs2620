gRPC Server Module
================

.. automodule:: src.chat_grpc_server
   :members:
   :undoc-members:
   :show-inheritance:

This module implements the gRPC server for the chat system with replication support. Key features include:

- Leader-follower replication protocol
- Account management (creation, login, deletion)
- Message handling and delivery
- Chat history management
- Server-to-server communication
- Automatic leader election
- State replication between servers

The server can operate in three roles:

1. Leader: Handles all client requests and replicates changes to followers
2. Follower: Forwards client requests to the leader and maintains a replica
3. Candidate: Temporarily assumed during leader election 