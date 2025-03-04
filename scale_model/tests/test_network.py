import socket
import time
from src.network import start_server, send_message


def cleanup_server_socket(server_socket):
    """Helper to properly clean up server socket and its thread."""
    if hasattr(server_socket, "stop_flag"):
        server_socket.stop_flag.set()  # Signal the thread to stop
    if hasattr(server_socket, "accept_thread"):
        server_socket.accept_thread.join(timeout=1.0)  # Wait for thread to finish
    server_socket.close()


def test_start_server_calls_message_handler():
    server = None
    try:
        # Collect messages received by the handler.
        messages = []

        def handler(msg):
            messages.append(msg)

        # Bind on port 0 so the OS picks an available port.
        server = start_server("127.0.0.1", 0, handler)
        host, port = server.getsockname()

        # Create a client that connects and sends a message.
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((host, port))
        test_msg = "Hello, Server!"
        client.sendall(test_msg.encode("utf-8"))
        client.close()

        # Give the server thread a moment to process the connection.
        time.sleep(0.1)
        assert messages == [test_msg]
    finally:
        if server:
            server.close()


def test_handle_client_exception(monkeypatch, capsys):
    server = None
    try:
        # Create a dummy message handler that does nothing.
        def dummy_handler(msg):
            pass

        # Create a fake socket class
        class FakeSocket:
            def __init__(self):
                self.bound = False
                self.listening = False
                self.closed = False
                self.accept_count = 0
                self.timeout = None

            def bind(self, addr):
                self.bound = True

            def listen(self):
                self.listening = True

            def getsockname(self):
                return ("127.0.0.1", 0)

            def close(self):
                self.closed = True

            def settimeout(self, timeout):
                self.timeout = timeout

            def accept(self):
                self.accept_count += 1
                if self.accept_count == 1:
                    return FakeClientSocket(), ("127.0.0.1", 12345)
                raise socket.timeout()

        class FakeClientSocket:
            def recv(self, bufsize):
                raise Exception("Fake recv exception")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        # Replace socket.socket with our fake socket
        def fake_socket(*args, **kwargs):
            return FakeSocket()

        monkeypatch.setattr(socket, "socket", fake_socket)

        # Start the server with our dummy handler
        server = start_server("127.0.0.1", 0, dummy_handler)

        # Give the server thread time to accept and process the fake connection
        time.sleep(0.2)

        # Capture output and assert that the error message was printed
        captured = capsys.readouterr().out
        assert "Error handling client: Fake recv exception" in captured
    finally:
        if server:
            server.close()


def test_send_message_success():
    server = None
    try:
        # Verify that send_message properly sends data.
        messages = []

        def handler(msg):
            messages.append(msg)

        server = start_server("127.0.0.1", 0, handler)
        host, port = server.getsockname()

        send_message(host, port, "Test Message")
        time.sleep(0.1)
        assert messages == ["Test Message"]
    finally:
        if server:
            server.close()


def test_send_message_failure(capsys):
    # Try connecting to a port where no server is listening.
    send_message("127.0.0.1", 9999, "Should fail")
    captured = capsys.readouterr().out
    assert "Error sending message" in captured
