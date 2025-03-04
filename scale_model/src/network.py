import socket
import threading


class ServerWrapper:
    """Wrapper class to hold server socket and its associated thread/flag."""

    def __init__(self, socket, thread, stop_flag):
        self.socket = socket
        self.thread = thread
        self.stop_flag = stop_flag

    def close(self):
        """Clean up resources."""
        self.stop_flag.set()
        self.thread.join(timeout=1.0)
        self.socket.close()

    def getsockname(self):
        """Delegate to underlying socket."""
        return self.socket.getsockname()


def start_server(host, port, message_handler):
    """
    Starts a TCP server on the specified host and port.
    For each incoming connection, it spawns a thread that reads a message and calls message_handler.
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((host, port))
    server_socket.listen()
    print(f"Socket server running on {host}:{port}")

    # Add a stop flag for clean shutdown
    stop_flag = threading.Event()

    def accept_connections():
        while not stop_flag.is_set():
            try:
                server_socket.settimeout(
                    0.5
                )  # Add timeout to check stop flag periodically
                try:
                    client_socket, addr = server_socket.accept()
                    threading.Thread(
                        target=handle_client,
                        args=(client_socket, message_handler),
                        daemon=True,
                    ).start()
                except socket.timeout:
                    continue  # Check stop flag and try again
            except Exception as e:
                if not stop_flag.is_set():  # Only print error if we're not stopping
                    print(f"Error accepting connection: {e}")

    def handle_client(client_socket, message_handler):
        with client_socket:
            try:
                data = client_socket.recv(1024)
                if data:
                    message = data.decode("utf-8").strip()
                    message_handler(message)
            except Exception as e:
                print(f"Error handling client: {e}")

    thread = threading.Thread(target=accept_connections, daemon=True)
    thread.start()

    return ServerWrapper(server_socket, thread, stop_flag)


def send_message(target_host, target_port, message):
    """
    Connects to the target machine and sends the message.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((target_host, target_port))
            sock.sendall(message.encode("utf-8"))
    except Exception as e:
        print(f"Error sending message to {target_host}:{target_port} -> {e}")
