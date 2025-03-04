# Distributed System with Logical Clocks

## Components

- `src/machine.py`: Implements the core `Machine` class that handles clock updates, message processing, and event logging
- `src/network.py`: Provides networking functionality for message passing between machines
- `main.py`: Entry point for starting individual machine instances

## Usage

To run a machine instance, use the following command:

```bash
python main.py --id <machine_id> --port <port_number> [--host <hostname>] [--neighbors <neighbor_list>]
```

### Arguments

- `--id`: Unique identifier for the machine (required)
- `--port`: Port number for the machine's server (required)
- `--host`: Hostname to bind the server (default: localhost)
- `--neighbors`: Comma-separated list of neighbor endpoints (format: host:port,host:port)

### Example Setup

To create a network of three machines:

```bash
# Terminal 1
python main.py --id 1 --port 8001 --neighbors localhost:8002,localhost:8003

# Terminal 2
python main.py --id 2 --port 8002 --neighbors localhost:8001,localhost:8003

# Terminal 3
python main.py --id 3 --port 8003 --neighbors localhost:8001,localhost:8002
```

### Running Tests

1. Run all tests:
```bash
run pytest
```

2. Run specific implementation tests:
```bash
run pytest tests/test_network.py
```

3. Run specific unit tests:
```bash
run pytest tests/test_machine.py::test_handle_incoming_message
```

4. Run tests with coverage:
```bash
run pytest --cov=src.machine
```

5. Generate HTML coverage report:
```bash
run pytest --cov=src --cov-report=html
```

The report will be available in `htmlcov/index.html`

### Coverage Metrics

| Module | Miss | Coverage |
|--------|-----------|----------|
| machine.py | 4 | 95% |
| network.py | 3 | 94% |
| **Total** | 7 | 94% |
