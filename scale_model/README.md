# Distributed System with Logical Clocks

## Components

- `src/machine.py`: Implements the core `Machine` class that handles clock updates, message processing, and event logging
- `src/network.py`: Provides networking functionality for message passing between machines
- `main.py`: Entry point for starting individual machine instances

## Setup

### Requirements

- Python 3.9+
- pipenv (for dependency management)

### Installation

All commands should be run from the `scale_model` directory:

1. Install Pipenv if you haven't already:
```bash
pip install pipenv
```

2. Install project dependencies:
```bash
# Install runtime dependencies
pipenv install

# Install development dependencies (for testing and documentation)
pipenv install --dev
```

## Usage

All commands below should be run from the `scale_model` directory.

To run a machine instance:

```bash
pipenv run python main.py --id <machine_id> --port <port_number> [--host <hostname>] [--neighbors <neighbor_list>]
```

### Arguments

- `--id`: Unique identifier for the machine (required)
- `--port`: Port number for the machine's server (required)
- `--host`: Hostname to bind the server (default: localhost)
- `--neighbors`: Comma-separated list of neighbor endpoints (format: host:port,host:port)

### Example Setup

To create a network of three machines (run each in a separate terminal from the `scale_model` directory):

```bash
# Terminal 1
pipenv run python main.py --id 1 --port 8001 --neighbors localhost:8002,localhost:8003

# Terminal 2
pipenv run python main.py --id 2 --port 8002 --neighbors localhost:8001,localhost:8003

# Terminal 3
pipenv run python main.py --id 3 --port 8003 --neighbors localhost:8001,localhost:8002
```

You can also run the `start_machines.py` script using default parameters with the command

```bash
pipenv run python start_machines.py
```
which will start three machines as listed in the commands above and run them for 60 seconds. You can also use the following options to set additional options:

`--clock_rate_min`: Minimum value for the machine’s random clock rate.\
`--clock_rate_max`: Maximum value for the machine’s random clock rate.\
`--internal_work_prob`: Probability (between 0 and 1) of performing internal work instead of sending messages.

## Development

All development commands should be run from the `scale_model` directory.

### Running Tests

Use the predefined Pipenv scripts for testing:

1. Run all tests:
```bash
pipenv run test
```

2. Run specific implementation tests:
```bash
pipenv run pytest tests/test_network.py
```

3. Run specific unit tests:
```bash
pipenv run pytest tests/test_machine.py::test_handle_incoming_message
```

4. Run tests with coverage:
```bash
pipenv run coverage
```

The coverage report will be available in `htmlcov/index.html`

### Documentation

Build and view the documentation:

```bash
pipenv run docs
```

The documentation will be available in `docs/_build/html/index.html`

### Code Formatting

Format the code using Black:

```bash
pipenv run format
```

### Coverage Metrics

| Module | Miss | Coverage |
|--------|-----------|----------|
| machine.py | 4 | 95% |
| network.py | 3 | 94% |
| **Total** | 7 | 94% |
