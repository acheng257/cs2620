import io
import time
import random
import queue
import pytest
from src.machine import Machine
import src.machine as machine


# Fixture to ensure that any file I/O writing to "logs/" goes to a temporary directory.
@pytest.fixture(autouse=True)
def setup_logs(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    original_open = open

    def fake_open(filename, mode="r", *args, **kwargs):
        if isinstance(filename, str) and filename.startswith("logs/"):
            # Write logs to the temporary logs directory.
            filename = str(logs_dir / filename.split("/")[-1])
        return original_open(filename, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)


# Helper to create a Machine instance with a fake log_file.
def create_machine(monkeypatch):
    m = Machine(
        id=1,
        host="127.0.0.1",
        port=5000,
        neighbors=[("127.0.0.1", 5001), ("127.0.0.1", 5002)],
    )
    m.log_file = io.StringIO()
    return m


def test_handle_incoming_message(monkeypatch):
    m = create_machine(monkeypatch)
    m.handle_incoming_message("Test incoming")
    # Check that the message was enqueued.
    assert not m.message_queue.empty()
    assert m.message_queue.get() == "Test incoming"


def test_receive_message(monkeypatch):
    m = create_machine(monkeypatch)
    m.clock = 5
    result = m.receive_message(sender_id=2, sender_timestamp=10, msg="Hello")
    # Clock should update to max(5,10)+1 = 11.
    assert result is True
    assert m.clock == 11
    # Verify the log entry.
    assert "RECEIVE" in m.log_file.getvalue()


def test_send_message(monkeypatch):
    m = create_machine(monkeypatch)
    calls = []

    # Replace just the network.send_message call, not the whole method
    def fake_send(target_host, target_port, message):
        calls.append((target_host, target_port, message))

    monkeypatch.setattr(machine, "send_message", fake_send)

    target_peer = ("127.0.0.1", 5001)
    m.send_message(target_peer, "Hi there")
    # Check that our fake_send was "called".
    assert calls == [("127.0.0.1", 5001, "Hi there")]
    # The machine's clock is incremented.
    assert m.clock == 1
    # And a SEND log entry was created.
    log_contents = m.log_file.getvalue()
    assert "SEND" in log_contents


def test_log_event(monkeypatch):
    m = create_machine(monkeypatch)
    m.clock = 7
    m.log_event("INTERNAL", "Internal work done.")
    log_contents = m.log_file.getvalue()
    assert "INTERNAL" in log_contents
    assert "[Machine=1]" in log_contents


# Helper to simulate time progression.
def fake_time_generator(values):
    def fake_time():
        return values.pop(0)

    return fake_time


def test_main_loop_with_message(monkeypatch):
    m = create_machine(monkeypatch)
    # Put a valid message in the queue.
    m.message_queue.put("2|3|Test Message")

    # Need more time values for all the time.time() calls
    times = [100.0] * 10  # Initial times for setup and logs
    times.extend([161.0] * 5)  # Times to trigger exit and cleanup
    monkeypatch.setattr(time, "time", fake_time_generator(times))
    monkeypatch.setattr(time, "sleep", lambda s: None)

    m.main_loop()
    # The log should include a RECEIVE event.
    log_contents = m.log_file.getvalue()
    assert "RECEIVE" in log_contents


@pytest.mark.parametrize(
    "rand_value, expected_target",
    [
        (1, ("127.0.0.1", 5001)),
        (2, ("127.0.0.1", 5002)),
    ],
)
def test_main_loop_send_branches(monkeypatch, rand_value, expected_target):
    m = create_machine(monkeypatch)
    m.running = True
    m.message_queue = queue.Queue()  # Ensure the queue is empty.
    send_calls = []

    def fake_send(target_host, target_port, message):
        send_calls.append(((target_host, target_port), message))

    monkeypatch.setattr(machine, "send_message", fake_send)

    # Force random.randint to return the desired branch value.
    monkeypatch.setattr(random, "randint", lambda a, b: rand_value)

    # Need more time values for all the time.time() calls
    times = [200.0] * 10  # Initial times for setup and logs
    times.extend([261.0] * 5)  # Times to trigger exit and cleanup
    monkeypatch.setattr(time, "time", fake_time_generator(times))
    monkeypatch.setattr(time, "sleep", lambda s: None)

    m.main_loop()
    # Check that the correct neighbor was chosen.
    assert send_calls
    target, msg = send_calls[0]
    assert target == expected_target
    assert "Hello from M1" in msg


def test_main_loop_branch_3(monkeypatch):
    m = create_machine(monkeypatch)
    m.running = True
    m.message_queue = queue.Queue()
    send_calls = []

    def fake_send(target_host, target_port, message):
        send_calls.append(((target_host, target_port), message))

    monkeypatch.setattr(machine, "send_message", fake_send)

    # Branch 3: send to all neighbors.
    monkeypatch.setattr(random, "randint", lambda a, b: 3)

    # Need more time values for all the time.time() calls
    times = [300.0] * 15  # More times needed for multiple sends
    times.extend([361.0] * 5)  # Times to trigger exit and cleanup
    monkeypatch.setattr(time, "time", fake_time_generator(times))
    monkeypatch.setattr(time, "sleep", lambda s: None)

    m.main_loop()
    # Expect a send call for each neighbor.
    assert len(send_calls) >= 2


def test_main_loop_branch_else(monkeypatch):
    m = create_machine(monkeypatch)
    m.running = True
    m.message_queue = queue.Queue()

    # Branch else: any random value not 1, 2, or 3 (e.g. 5).
    monkeypatch.setattr(random, "randint", lambda a, b: 5)

    # Need more time values for all the time.time() calls
    times = [400.0] * 10  # Initial times for setup and logs
    times.extend([461.0] * 5)  # Times to trigger exit and cleanup
    monkeypatch.setattr(time, "time", fake_time_generator(times))
    monkeypatch.setattr(time, "sleep", lambda s: None)

    m.main_loop()
    # In this branch, only an INTERNAL event should be logged.
    log_contents = m.log_file.getvalue()
    assert "INTERNAL" in log_contents


def test_run(monkeypatch):
    m = create_machine(monkeypatch)
    calls = []
    # Replace start_network and main_loop with functions that record that they were called.
    m.start_network = lambda: calls.append("start_network")
    m.main_loop = lambda: calls.append("main_loop")
    m.run()
    assert calls == ["start_network", "main_loop"]
