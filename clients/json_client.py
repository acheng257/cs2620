import socket
import json
import time
import jsonschema  # Import jsonschema for validation
from datetime import datetime

HOST = "127.0.0.1"
PORT = 54400

with open("protocols/protocol.json", "r") as schema_file:
    SCHEMA = json.load(schema_file)

def validate_json(data):
    """Validates JSON request against the schema."""
    try:
        jsonschema.validate(instance=data, schema=SCHEMA)
        return True, None
    except jsonschema.ValidationError as e:
        return False, str(e)

# Example request
request = {
    "request_type": "SendMessage",
    "timestamp": datetime.utcnow().isoformat(),
    "data": {
        "sender": "Client1",
        "receiver": "Server",
        "message": "Hello, server!"
    }
}

is_valid, error_message = validate_json(request)
if not is_valid:
    print(f"Error: Invalid JSON request - {error_message}")
    exit(1)

json_request = json.dumps(request)

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((HOST, PORT))
    s.sendall(json_request.encode("utf-8"))

    time.sleep(1)  # Small delay to allow response

    data = s.recv(1024)  # Receive response from server

    print(f"Raw response from server: {data}")

    try:
        response = json.loads(data.decode("utf-8"))
        print(f"Received Response: {json.dumps(response, indent=4)}")
    except json.JSONDecodeError:
        print("Received malformed response from server")
