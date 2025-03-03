import socket
import threading


def start_server(host, port, message_handler):
    """
    Starts a TCP server on the specified host and port.
    For each incoming connection, it spawns a thread that reads a message and calls message_handler.
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((host, port))
    server_socket.listen()
    print(f"Socket server running on {host}:{port}")

    def accept_connections():
        while True:
            client_socket, addr = server_socket.accept()
            threading.Thread(
                target=handle_client, args=(client_socket, message_handler), daemon=True
            ).start()

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
    return server_socket


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
