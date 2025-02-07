import socket
import selectors
import types
import struct
from protocols.binary_utils import *

sel = selectors.DefaultSelector()

def process_binary_request(data):
    """Process incoming binary requests."""
    try:
        if len(data) < 3:  # Ensure the message has at least the header
            return encode_message(0xFF, encode_string("Error: Invalid request format"))

        # Unpack header
        msg_type, payload_size = struct.unpack_from("!BH", data, 0)

        if len(data) < 3 + payload_size:
            return encode_message(0xFF, encode_string("Error: Incomplete request data"))

        # Extract payload
        payload = data[3: 3 + payload_size]

        # Process message based on type
        if msg_type == MESSAGE_TYPES["SEND_MESSAGE"]:
            sender, offset = decode_string(payload, 0)
            receiver, offset = decode_string(payload, offset)
            message, _ = decode_string(payload, offset)
            
            print(f"Message from {sender} to {receiver}: {message}")
            return encode_message(MESSAGE_TYPES["SEND_MESSAGE"], encode_string("Message received"))

        elif msg_type == MESSAGE_TYPES["CREATE_ACCOUNT"]:
            username, _ = decode_string(payload, 0)
            return encode_message(MESSAGE_TYPES["CREATE_ACCOUNT"], encode_string(f"Account for {username} created"))
        # TODO: add the remaining message types

        else:
            return encode_message(0xFF, encode_string("Error: Unknown request type"))

    except Exception as e:
        return encode_message(0xFF, encode_string(f"Error: {str(e)}"))

def service_connection(key, mask):
    """Handles client-server communication."""
    sock = key.fileobj
    data = key.data
    if mask & selectors.EVENT_READ:
        recv_data = sock.recv(1024)
        if recv_data:
            response = process_binary_request(recv_data)
            sock.sendall(response)

if __name__ == "__main__":
    HOST, PORT = "127.0.0.1", 54400 # TODO: don't hardcode this
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.bind((HOST, PORT))
    lsock.listen()
    lsock.setblocking(False)
    sel.register(lsock, selectors.EVENT_READ, data=None)

    print(f"Listening on {HOST}:{PORT}")
    
    try:
        while True:
            events = sel.select(timeout=None)
            for key, mask in events:
                if key.data is None:
                    conn, addr = key.fileobj.accept()
                    conn.setblocking(False)
                    data = types.SimpleNamespace(addr=addr, inb=b"", outb=b"")
                    sel.register(conn, selectors.EVENT_READ | selectors.EVENT_WRITE, data=data)
                else:
                    service_connection(key, mask)
    except KeyboardInterrupt:
        print("Server shutting down.")
    finally:
        sel.close()
