import socket
import threading


class ServerWrapper:
    """
    A wrapper class for managing a TCP server socket and its associated thread.

    This class encapsulates the server socket, its accept thread, and a stop flag
    for clean shutdown. It provides methods for resource cleanup and socket operations.

    Attributes:
        socket (socket.socket): The underlying TCP server socket
        thread (threading.Thread): Thread handling incoming connections
        stop_flag (threading.Event): Event flag for signaling thread shutdown
    """

    def __init__(self, socket, thread, stop_flag):
        """
        Initialize a ServerWrapper instance.

        Args:
            socket (socket.socket): TCP server socket
            thread (threading.Thread): Accept thread for handling connections
            stop_flag (threading.Event): Event flag for signaling shutdown
        """
        self.socket = socket
        self.thread = thread
        self.stop_flag = stop_flag

    def close(self):
        """
        Clean up server resources.

        Sets the stop flag to terminate the accept thread, waits for thread completion,
        and closes the server socket.
        """
        self.stop_flag.set()
        self.thread.join(timeout=1.0)
        self.socket.close()

    def getsockname(self):
        """
        Get the socket's bound address and port.

        Returns:
            tuple: A (host, port) tuple indicating the socket's bound address
        """
        return self.socket.getsockname()


def start_server(host, port, message_handler):
    """
    Start a TCP server that handles incoming connections in separate threads.

    Creates a TCP server socket bound to the specified host and port. For each incoming
    connection, spawns a new thread to handle message reception. Messages are processed
    using the provided message handler function.

    Args:
        host (str): Host address to bind the server
        port (int): Port number to bind the server
        message_handler (callable): Function to process received messages

    Returns:
        ServerWrapper: A wrapper containing the server socket and management thread
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
        """
        Handle a client connection by receiving and processing a message.

        Args:
            client_socket (socket.socket): Socket for the client connection
            message_handler (callable): Function to process the received message
        """
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
    Send a message to a specific target machine.

    Creates a TCP connection to the target host and port, sends the message,
    and automatically closes the connection when complete.

    Args:
        target_host (str): Host address of the target machine
        target_port (int): Port number of the target machine
        message (str): Message to send
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((target_host, target_port))
            sock.sendall(message.encode("utf-8"))
    except Exception as e:
        print(f"Error sending message to {target_host}:{target_port} -> {e}")
