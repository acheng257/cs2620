import socket
import selectors
import types
import json
import os
import argparse
import jsonschema

sel = selectors.DefaultSelector()

DEFAULT_HOST = os.getenv("CHAT_SERVER_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("CHAT_SERVER_PORT", 54400))

parser = argparse.ArgumentParser(description="Start the chat server.")
parser.add_argument("--host", type=str, default=DEFAULT_HOST, help="Host address to bind to")
parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port number to listen on")
args = parser.parse_args()

with open("../protocols/protocol.json", "r") as schema_file:
    SCHEMA = json.load(schema_file)

def validate_json(data):
    try:
        jsonschema.validate(instance=data, schema=SCHEMA)
        return True, None
    except jsonschema.ValidationError as e:
        return False, str(e)

def accept_wrapper(sock):
    conn, addr = sock.accept()
    print(f"Accepted connection from {addr}")
    conn.setblocking(False)
    data = types.SimpleNamespace(addr=addr, inb=b"", outb=b"")
    events = selectors.EVENT_READ | selectors.EVENT_WRITE
    sel.register(conn, events, data=data)

def process_request(json_data):
    try:
        request = json.loads(json_data)
        print("Request is", request)
        
        # Validate JSON against schema
        is_valid, error_message = validate_json(request)
        if not is_valid:
            return json.dumps({"status": "error", "message": f"Schema validation failed: {error_message}"})

        request_type = request["request_type"]

        if request_type == "SendMessage":
            sender = request["data"].get("sender", "Unknown")
            message = request["data"].get("message", "No message")
            print(f"Message from {sender}: {message}")
            return json.dumps({"status": "success", "message": "Message received"})

        elif request_type == "CreateAccount":
            username = request["user_data"].get("username", "Unknown")
            return json.dumps({"status": "success", "message": f"Account created for {username}"})

        elif request_type == "DeleteAccount":
            username = request["user_data"].get("username", "Unknown")
            return json.dumps({"status": "success", "message": f"Account {username} deleted"})

        elif request_type == "UserLogin":
            username = request["user_data"].get("username", "Unknown")
            return json.dumps({"status": "success", "message": f"User {username} logged in"})

        elif request_type == "ReadMessage":
            limit = request["data"].get("limit", 10)
            return json.dumps({"status": "success", "messages": ["Sample message 1", "Sample message 2"][:limit]})

        elif request_type == "DeleteMessages":
            message_ids = request["data"].get("message_ids", [])
            return json.dumps({"status": "success", "message": f"Deleted {len(message_ids)} messages"})

        else:
            return json.dumps({"status": "error", "message": "Unknown request type"})
    
    except json.JSONDecodeError:
        return json.dumps({"status": "error", "message": "Invalid JSON format"})

def service_connection(key, mask):
    sock = key.fileobj
    data = key.data
    if mask & selectors.EVENT_READ:
        recv_data = sock.recv(1024)
        if recv_data:
            data.outb += recv_data
        else:
            return
    if mask & selectors.EVENT_WRITE:
        if data.outb:
            try:
                return_data = process_request(data.outb.decode("utf-8"))
                
                return_data = return_data + "\n"  # add newline as delimiter to separate responses
                print(f"Sending response to client: {return_data}")

                sock.sendall(return_data.encode("utf-8"))

                data.outb = b""  # Clear buffer after sending response

            except Exception as e:
                print(f"Error in processing request: {e}")
                sock.sendall(json.dumps({"status": "error", "message": "Internal server error"}).encode("utf-8"))


if __name__ == "__main__":
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.bind((args.host, args.port))
    lsock.listen()
    print(f"Listening on {args.host}:{args.port}")
    lsock.setblocking(False)
    sel.register(lsock, selectors.EVENT_READ, data=None)
    
    try:
        while True:
            events = sel.select(timeout=None)
            for key, mask in events:
                if key.data is None:
                    accept_wrapper(key.fileobj)
                else:
                    service_connection(key, mask)
    except KeyboardInterrupt:
        print("Caught keyboard interrupt, exiting")
    finally:
        sel.close()
