import socket
import time

HOST = "127.0.0.1"
PORT = 54400

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((HOST, PORT))
    s.sendall(b"Hello world")
    time.sleep(1)
    data = s.recv(1024)

print(f"Received: {data.decode()}")
