# CS262 Wire Protocols Project

This project implements a client-server chat application with support for multiple wire protocols (JSON and Binary).

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

1. **Test Workflow** (`test.yml`):
   - Runs the test suite on all branches and PRs
   - Generates and uploads coverage reports to Codecov
   - Creates a dynamic coverage badge
   - Archives test results as artifacts
   - Runs on Python 3.13

2. **Lint Workflow** (`lint.yml`):
   - Runs flake8 for code style checking
   - Performs type checking with mypy
   - Ensures code quality standards are met

3. **Format Workflow** (`format.yml`):
   - Checks code formatting with black
   - Verifies import ordering with isort
   - Maintains consistent code style

The workflows run automatically on:
- Every push to any branch
- Pull request creation/updates to main branch

Status badges:
![Tests](https://github.com/YOUR_USERNAME/cs2620/actions/workflows/test.yml/badge.svg)
![Coverage](https://img.shields.io/codecov/c/github/YOUR_USERNAME/cs2620)
![Lint](https://github.com/YOUR_USERNAME/cs2620/actions/workflows/lint.yml/badge.svg)
![Format](https://github.com/YOUR_USERNAME/cs2620/actions/workflows/format.yml/badge.svg)

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