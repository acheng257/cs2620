# Chat Application with Custom Wire Protocol

A client-server chat application that implements both a custom wire protocol and JSON-based communication for message exchange. This project was developed as part of Harvard's CS262 course.

## Technical Implementation

### Architecture

The application follows a client-server architecture with the following components:

1. **Server**
   - Handles multiple concurrent client connections
   - Manages user authentication and session state
   - Implements message routing and storage
   - Supports both wire protocol implementations

2. **Client**
   - Provides a graphical user interface
   - Handles user input and display
   - Implements protocol serialization/deserialization
   - Manages connection state and reconnection

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

### Running the Server

```bash
# Activate the virtual environment
pipenv shell

# Run the server
python server.py [--port PORT] [--protocol {binary,json}]
```

### Running the Client

```bash
# Activate the virtual environment (if not already activated)
pipenv shell

# Run the client
python client.py [--host HOST] [--port PORT] [--protocol {binary,json}]
```

### Running the Streamlit Interface

The application provides a modern web interface using Streamlit for a better user experience:

```bash
# Activate the virtual environment (if not already activated)
pipenv shell

# Run the Streamlit app
streamlit run app.py

# The app will automatically open in your default web browser
# Default URL: http://localhost:8501
```

## Configuration

The application can be configured through command-line arguments like shown in the previous section.

### Performance Implications
- Binary protocol reduces network bandwidth
- JSON protocol easier to debug and modify
- Tradeoff between efficiency and maintainability
