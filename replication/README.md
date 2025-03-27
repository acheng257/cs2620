# Replicated Chat System

A fault-tolerant, replicated chat application built with gRPC and Python. The system implements a leader-follower replication protocol to provide high availability and consistency in the face of server failures.

## Project Structure
```
.
├── README.md
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── chat_grpc_server.py
│   ├── chat_grpc_client.py
│   ├── database/
│   │   ├── __init__.py
│   │   └── db_manager.py
│   ├── replication/
│   │   ├── __init__.py
│   │   └── replication_manager.py
│   └── protocols/
│       └── grpc/
│           ├── chat.proto
│           ├── chat_pb2.py
│           ├── chat_pb2.pyi
│           └── chat_pb2_grpc.py
├── docs/                  # Documentation files
├── pyproject.toml        # Project configuration
├── Pipfile              # Dependencies
├── tests/
│   ├── __init__.py
│   ├── test_grpc_server.py
│   ├── test_grpc_client.py
│   ├── test_replication.py
│   └── test_database.py
└── grpc_app.py          # Streamlit UI
```

## Features

- **Fault Tolerance**: Survives up to 2 server failures while maintaining service
- **Strong Consistency**: All operations are replicated across servers with majority acknowledgment
- **Automatic Leader Election**: Handles leader failures with automatic failover
- **Persistent Storage**: Messages and account data survive server restarts
- **Dynamic Cluster Configuration**: Supports adding new replicas to the cluster
- **Real-time Communication**: Instant message delivery with read/delivery status
- **Modern Web Interface**: Streamlit-based UI with real-time updates

## Architecture

### Components

1. **Chat Server (`chat_grpc_server.py`)**
   - Implements the leader-follower replication protocol
   - Handles client requests and inter-server communication
   - Manages persistent storage through SQLite
   - Coordinates leader election and state replication

2. **Chat Client (`chat_grpc_client.py`)**
   - Provides high-level interface for server communication
   - Implements automatic leader discovery and reconnection
   - Handles message sending, receiving, and account management
   - Maintains background threads for real-time updates

3. **Web Interface (`grpc_app.py`)**
   - Streamlit-based web application
   - Real-time chat interface with message history
   - Account management and server configuration
   - Automatic reconnection on leader changes

4. **Database (`db_manager.py`)**
   - Manages SQLite database for account and message storage
   - Provides methods for account creation, message sending, and retrieval

5. **Replication Manager (`replication_manager.py`)**
   - Manages the replication protocol
   - Handles leader election and state replication
   - Provides methods for message sending, account creation, and deletion
   - Handles heartbeat monitoring and failure detection

### Replication Protocol

The system uses a leader-follower protocol where:
- One server acts as the leader, handling all client requests
- Followers maintain replicas and participate in leader election
- Leader election uses a term-based voting system
- Write operations require majority acknowledgment
- Automatic failover when leader becomes unavailable

## Getting Started

### Prerequisites

- Python 3.7+
- gRPC tools and runtime
- SQLite3
- Required Python packages:
  ```bash
  pip install grpcio grpcio-tools protobuf streamlit streamlit-autorefresh
  ```

### Running the System

1. **Generate gRPC Code**
   ```bash
   # Generate Python gRPC code from proto definitions
   python -m grpc_tools.protoc -I. --python_out=. --pyi_out=. --grpc_python_out=. src/protocols/grpc/chat.proto
   ```

2. **Start Multiple Server Instances**
   ```bash
   # Start the first server (potential leader)
   python chat_grpc_server.py --host 0.0.0.0 --port 50051
   
   # Start additional replicas
   python chat_grpc_server.py --host 0.0.0.0 --port 50052 --replicas 127.0.0.1:50051
   python chat_grpc_server.py --host 0.0.0.0 --port 50053 --replicas 127.0.0.1:50051 127.0.0.1:50052
   ```

3. **Launch the Web Interface**
   ```bash
   # Connect to the cluster
   streamlit run grpc_app.py -- --cluster-nodes "127.0.0.1:50051,127.0.0.1:50052,127.0.0.1:50053"
   ```

### Logging Configuration

The system provides detailed logging with different verbosity levels for different components:

1. **Server Logging**
   - Controls general server operations logging
   - Set level with `--log-level` argument
   - Available levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
   - Default level: INFO
   ```bash
   # Example: Run server with debug logging
   python chat_grpc_server.py --host 0.0.0.0 --port 50051 --log-level DEBUG
   ```

2. **Heartbeat Logging**
   - Controls leader-follower heartbeat logging
   - Set level with `--heartbeat-log-level` argument
   - Available levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
   - Default level: WARNING (to reduce noise)
   ```bash
   # Example: Enable detailed heartbeat logging
   python chat_grpc_server.py --host 0.0.0.0 --port 50051 --heartbeat-log-level DEBUG
   ```

3. **Log Format**
   - Timestamp: When the event occurred
   - Level: Severity level (DEBUG/INFO/WARNING/ERROR/CRITICAL)
   - Server Info: Host:Port of the server
   - Message: Detailed event description
   ```
   2024-03-20 10:15:30 - INFO - [127.0.0.1:50051] Server started with 2 replicas
   ```

4. **Color Coding**
   - DEBUG/INFO: Grey (normal operations)
   - WARNING: Yellow (potential issues)
   - ERROR/CRITICAL: Red (serious problems)

### Testing Fault Tolerance

1. **Server Failure Simulation**
   - Stop any server using Ctrl+C
   - The system will automatically:
     - Detect the failure
     - Elect a new leader if needed
     - Maintain service availability
     - Replicate state to remaining servers

2. **Leader Failover**
   - Stop the current leader server
   - Observe automatic leader election
   - Verify continued service with new leader
   - Check data consistency across replicas

3. **Adding New Replicas**
   - Start a new server instance
   - Specify existing cluster nodes
   - Watch state synchronization
   - Verify participation in replication

## Testing Guide

### Test Organization

```
tests/
├── conftest.py           # Shared test fixtures
├── test_grpc_server.py   # Server and replication tests
├── test_grpc_client.py   # Client and connection tests
├── test_replication.py   # Replication protocol tests
└── test_database.py      # Database operation tests
```

### Running Tests

1. Run all tests:
```bash
pytest
```

2. Run specific test files:
```bash
# Server and replication tests
pytest tests/test_grpc_server.py

# Client tests
pytest tests/test_grpc_client.py

# Database tests
pytest tests/test_database.py
```

3. Run specific test case:
```bash
pytest tests/test_grpc_server.py::test_function_name
```

4. Run tests with coverage:
```bash
# Generate coverage report
pytest --cov=src tests/

# Generate HTML coverage report
pytest --cov=src --cov-report=html
```

## Documentation

The project uses Sphinx for documentation generation:

1. Install documentation dependencies:
```bash
pip install sphinx sphinx-rtd-theme
```

2. Build the documentation:
```bash
cd docs
make html
```

3. View the documentation by opening `docs/build/html/index.html`

### Documentation Style

Use Google-style docstrings for Python code:
```python
def function_name(param1: type1, param2: type2) -> return_type:
    """Short description of what the function does.

    Args:
        param1: Description of param1
        param2: Description of param2

    Returns:
        Description of return value

    Raises:
        ErrorType: Description of when this error is raised
    """
```

## Implementation Details

### Data Persistence

Each server maintains its own SQLite database containing:
- User accounts and authentication data
- Message history with delivery status
- Chat partner relationships
- Server configuration and state

### Leader Election

The leader election protocol ensures:
- At most one leader per term
- Majority vote requirement
- Automatic term increment on timeouts
- Prevention of split-brain scenarios
- Fast failure detection and recovery

### State Replication

Write operations follow this flow:
1. Client sends request to any server
2. Non-leader servers forward to leader
3. Leader validates and processes request
4. Leader replicates to followers
5. Leader waits for majority acknowledgment
6. Leader commits and responds to client

### Failure Handling

The system handles various failure scenarios:
- Server crashes (up to 2 simultaneous)
- Network partitions
- Leader failures
- Client disconnections
- Database corruption

## API Documentation

### Server Methods

- `CreateAccount`: Create new user account
- `Login`: Authenticate user
- `SendMessage`: Send chat message
- `Subscribe`: Real-time message subscription
- `ReadConversation`: Get chat history
- `DeleteMessages`: Remove messages
- `ListChatPartners`: Get active chats
- `GetLeader`: Query current leader

### Client Methods

- `connect()`: Establish server connection
- `login(username, password)`: Authenticate
- `send_message(recipient, text)`: Send message
- `start_read_thread()`: Begin message polling
- `read_conversation(partner)`: Get chat history

## Code Quality

The project uses several tools to maintain code quality:

```bash
# Format code
black . --config=./pyproject.toml
isort . --settings-file=./pyproject.toml

# Run linting
flake8 . --count --max-line-length=100 --statistics
mypy . --config=./pyproject.toml --ignore-missing-imports
```

## Performance Metrics

### gRPC Protocol Performance
- Serialization: 0.036ms (avg)
- Deserialization: 0.059ms (avg)
- Message size reduction: 57-76% vs JSON
- Type safety and code generation benefits
- Built-in streaming support
- Automatic client/server code generation
