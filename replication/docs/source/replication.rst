Replication Module
=================

.. automodule:: src.replication.replication_manager
   :members:
   :undoc-members:
   :show-inheritance:

This module implements the replication protocol for the distributed chat system. Features include:

- Leader election using Raft consensus
- State replication between servers
- Automatic failover handling
- Cluster membership management
- Heartbeat monitoring
- Log consistency checking
- Conflict resolution

The replication protocol ensures:

1. Strong consistency for all operations
2. Automatic leader election on failure
3. Majority acknowledgment for changes
4. Automatic client redirection to leader 