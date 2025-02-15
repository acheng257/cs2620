# Chat Application with Custom Wire Protocol

A client-server chat application that implements both a custom wire protocol and JSON-based communication for message exchange. This project was developed as part of Harvard's CS262 course.

## Project Structure

```
.
├── app.py                  # Streamlit web interface
├── src/
│   ├── server.py          # Main server implementation
│   ├── client.py          # Base client implementation (used by app.py)
│   ├── protocols/
│   │   ├── __init__.py
│   │   ├── base.py           # Protocol interface
│   │   ├── binary_protocol.py # Custom binary protocol
│   │   └── json_protocol.py   # JSON protocol implementation
│   └── database/
│       └── db_manager.py     # Database operations manager
├── tests/
│   ├── conftest.py           # Test configurations and fixtures
│   ├── test_server.py        # Server tests
│   ├── test_client.py        # Client tests
│   ├── test_protocols.py     # Protocol tests
│   └── test_database.py      # Database tests
├── docs/                  # Documentation files
├── pyproject.toml        # Project configuration
├── Pipfile              # Dependencies
└── README.md
```

## Overview

This chat application allows users to create accounts, send messages, and manage their communications through a centralized server. The system implements two different wire protocols for comparison: a custom binary protocol optimized for efficiency, and a JSON-based protocol for readability and compatibility.

## Features

- **Account Management**
  - Create new accounts with password protection
  - Login with secure password verification
  - Delete accounts with configurable message handling
  - List accounts with pattern matching

- **Messaging Capabilities**
  - Send messages to other users
  - Real-time message delivery for online users
  - Message queuing for offline users
  - Configurable message retrieval (specify number of messages)
  - Message deletion functionality

## Technical Implementation

### Architecture

The application follows a modern client-server architecture with the following components:

1. **Server (`src/server.py`)**
   - Handles multiple concurrent client connections using asyncio
   - Manages user authentication and session state
   - Implements message routing and storage
   - Supports both wire protocol implementations
   - Provides WebSocket endpoints for Streamlit client communication

2. **Streamlit Client (`app.py`)**
   - Modern web-based user interface
   - Real-time message updates
   - Multiple client instances can connect simultaneously
   - Responsive design for desktop and mobile
   - Built-in error handling and reconnection logic

3. **Protocol Layer (`src/protocols/`)**
   - Abstract base protocol interface
   - Binary protocol implementation for efficiency
   - JSON protocol implementation for debugging
   - Extensible design for adding new protocols

4. **Database Layer (`src/database/`)**
   - SQLite database for persistent storage
   - Asynchronous database operations
   - Transaction management
   - Connection pooling

### Wire Protocols

#### Custom Binary Protocol
Our custom protocol is designed for efficiency with minimal overhead:
- Fixed-length headers for quick parsing
- Binary encoding for numeric values
- Length-prefixed variable data
- Optimized message types for common operations

#### JSON Protocol
The JSON implementation provides:
- Human-readable message format
- Standard encoding/decoding
- Easy debugging and monitoring
- Compatibility with existing tools

### Security Features

- Passwords are never transmitted in plaintext
- Session-based authentication
- Input validation and sanitization
- Secure message storage

## Getting Started

### Prerequisites

1. Install Pipenv if you haven't already:
```bash
pip install pipenv
```

2. Install project dependencies:
```bash
# Clone the repository
git clone [repository-url]
cd cs2620

# Install dependencies using Pipenv
pipenv install

# Install development dependencies (for testing)
pipenv install --dev
```

### Running the Application

1. Start the Server:
```bash
# Activate the virtual environment
pipenv shell

# Run the server (default port: 8000)
python src/server.py [--port PORT] [--protocol {binary,json}]
```

2. Launch the Streamlit Interface:
```bash
# In a new terminal, activate the virtual environment
pipenv shell

# Run the Streamlit app (default port: 8501)
streamlit run app.py
```

You can run multiple streamlit clients to simulate different clients connecting to the server. Each instance will maintain its own connection and state.

### Configuration Options

Server:
- `--port PORT`: Server port (default: 8000)
- `--protocol {binary,json}`: Wire protocol to use (default: binary)

Streamlit:
- Automatically connects to the server using WebSocket
- Configuration can be modified inside the interface.

## Testing Guide

The project uses pytest for testing with the following structure:

### Test Organization

```
tests/
├── conftest.py           # Shared test fixtures and configurations
├── test_server.py        # Server endpoint and protocol tests
├── test_client.py        # Client communication tests
└── test_database.py      # Database operation tests
```

### Key Test Components

1. **Server Tests**
   - WebSocket connection handling
   - Protocol message processing
   - Concurrent client management
   - Error handling and recovery

2. **Client Tests**
   - Message serialization/deserialization
   - Connection management
   - UI state management
   - Error handling

3. **Database Tests**
   - CRUD operations
   - Transaction management
   - Concurrent access
   - Data integrity

## Configuration

The application can be configured through command-line arguments and inside the streamlit interface like shown in the previous sections.

## Linting and Formatting

The project uses black and isort for code formatting, and flake8 and mypy for linting. The configuration is in `pyproject.toml`.

```bash
# Run code formatting
black . --config=./pyproject.toml
isort . --settings-file=./pyproject.toml

# Run linting
flake8 . --count --max-line-length=100 --statistics
mypy . --config=./pyproject.toml --ignore-missing-imports
```

## Documentation

### Generating Documentation

The project uses Sphinx to automatically generate documentation from the codebase. To generate the documentation:

1. Install documentation dependencies:
```bash
pipenv install --dev sphinx sphinx-rtd-theme
```

2. Build the documentation:
```bash
cd docs
pipenv run make html
```

3. View the documentation by opening `docs/build/html/index.html` in your web browser.

### Documentation Structure

The documentation includes:
- Complete API reference
- Module listings
- Class and function documentation with source code links
- Full text search functionality
- Index of all modules, classes, and functions

### Updating Documentation

When adding new code or making changes:

1. Add Google-style docstrings to your Python functions and classes:
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

2. Rebuild the documentation to reflect your changes:
```bash
cd docs
pipenv run make html
```

## Protocol Comparison (TODO)

### Message Size Comparison
| Operation          | Binary Protocol | JSON Protocol |
|-------------------|-----------------|---------------|
| Login Request     | XX bytes        | YY bytes      |
| Message Send      | XX bytes        | YY bytes      |
| Account List      | XX bytes        | YY bytes      |

### Performance Implications
- Binary protocol reduces network bandwidth
- JSON protocol easier to debug and modify
- Tradeoff between efficiency and maintainability
