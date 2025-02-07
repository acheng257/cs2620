import socket
from protocols.binary_utils import *

HOST = "127.0.0.1"
PORT = 54400

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((HOST, PORT))
    
    request = send_message("Alice", "Bob", "Hello in binary!")
    s.sendall(request)

    data = s.recv(1024)
    print("Raw Response Data:", data)

    if not data:
        print("Error: Received empty response from server.")
    elif len(data) < 3:  # 1-byte message type + 2-byte payload length
        print("Error: Response is too short.")
    else:
        msg_type, payload_size = struct.unpack_from("!BH", data, 0)
        
        if len(data) < 3 + payload_size:
            print(f"Error: Expected {3 + payload_size} bytes, but got {len(data)}.")
        else:
            # Decode the payload (expected to be a string)
            try:
                response, _ = decode_string(data, 3)  # Start decoding after header
                print("Response:", response)
            except Exception as e:
                print(f"Error decoding response: {e}")
