# Chat Application with Custom Wire Protocol

A client-server chat application that implements both a custom wire protocol and JSON-based communication for message exchange. This project was developed as part of Harvard's CS262 course.

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

## Testing Guide

### Prerequisites

Make sure you have the following installed:
- Python 3.8 or higher
- pipenv (for dependency management)

### Setting Up the Development Environment

1. Clone the repository:
```bash
git clone <repository-url>
cd cs2620
```

2. Install dependencies using pipenv:
```bash
pipenv install
pipenv shell
```

3. Install test dependencies:
```bash
pipenv install pytest pytest-cov pytest-asyncio
```

### Running Tests

#### Basic Test Commands

1. Run all tests:
```bash
pytest
```

2. Run tests with verbose output:
```bash
pytest -v
```

3. Run tests with coverage report:
```bash
pytest --cov=protocols
```

4. Generate HTML coverage report:
```bash
pytest --cov=protocols --cov-report=html
```

#### Running Specific Tests

1. Run tests from a specific file:
```bash
pytest tests/test_protocols.py
```

2. Run tests for a specific protocol:
```bash
pytest tests/test_protocols.py::TestJsonProtocol
pytest tests/test_protocols.py::TestBinaryProtocol
```

3. Run a specific test method:
```bash
pytest tests/test_protocols.py::TestJsonProtocol::test_serialize_deserialize
```

4. Run tests matching a pattern:
```bash
pytest -k "serialize"  # runs all tests with "serialize" in the name
```

### Test Structure

The test suite is organized as follows:

#### Fixtures (`tests/test_protocols.py`)
- `json_protocol`: Creates a JsonProtocol instance
- `binary_protocol`: Creates a BinaryProtocol instance
- `sample_messages`: Provides sample messages for testing different scenarios

#### Test Classes

1. `TestJsonProtocol`:
   - Tests JSON serialization/deserialization
   - Tests error handling
   - Tests protocol naming
   - Tests message size calculation

2. `TestBinaryProtocol`:
   - Tests Binary serialization/deserialization
   - Tests error handling
   - Tests protocol naming
   - Tests message size calculation
   - Tests handling of empty fields

3. Protocol Comparison Tests:
   - Compares message sizes between protocols
   - Provides performance metrics

### Coverage Reports

The project is configured to generate coverage reports using pytest-cov. The configuration in `pyproject.toml` specifies:

- Source directory to measure: `protocols/`
- Excluded paths: `tests/*`
- Coverage report format: term-missing (shows lines that aren't covered)

To view detailed coverage information:
1. Run tests with HTML coverage report:
```bash
pytest --cov=protocols --cov-report=html
```
2. Open `htmlcov/index.html` in your browser

### Writing New Tests

When adding new tests:

1. Follow the existing test structure
2. Use appropriate fixtures
3. Add docstrings explaining test purpose
4. Ensure proper error handling is tested
5. Add edge cases where appropriate

### Continuous Integration

The project uses GitHub Actions for CI/CD with three main workflows:

1. **Lint Workflow** (`lint.yml`):
   - Runs flake8 for code style checking
   - Performs type checking with mypy
   - Ensures code quality standards are met

2. **Format Workflow** (`format.yml`):
   - Checks code formatting with black
   - Verifies import ordering with isort
   - Maintains consistent code style

The workflows run automatically on:
- Every push to any branch
- Pull request creation/updates to main branch

### Common Issues and Solutions

1. **ModuleNotFoundError: No module named 'protocols'**
   - Make sure you're running tests from the project root
   - Verify that `protocols/__init__.py` exists
   - Check that `PYTHONPATH` includes the project root

2. **Import errors in tests**
   - Ensure all dependencies are installed in your pipenv environment
   - Verify you're using the correct Python version

3. **Coverage reports not generating**
   - Make sure pytest-cov is installed
   - Check `pyproject.toml` configuration

### Best Practices

1. Always run tests before committing changes
2. Maintain test coverage above 90%
3. Write descriptive test names and docstrings
4. Test both success and failure cases
5. Keep tests independent and isolated

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

## Project Structure

```
.
├── pyproject.toml
├── Pipfile
├── Pipfile.lock
├── tests/
│   ├── test_server.py
│   └── test_client.py
├── README.md
├── app.py
└── src/
    ├── server.py
    ├── client.py
    ├── protocols/
    │   ├── binary_protocol.py
    │   ├── json_protocol.py
    │   └── base.py
    └── database/
        └── db_manager.py
```
