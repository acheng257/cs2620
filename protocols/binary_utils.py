import struct
import time
import hashlib

MESSAGE_TYPES = {
    "CREATE_ACCOUNT": 0x01,
    "LOGIN": 0x02,
    "SEND_MESSAGE": 0x03,
    "READ_MESSAGE": 0x04,
    "DELETE_MESSAGE": 0x05,
    "DELETE_ACCOUNT": 0x06,
}

# TODO: hash passwords
def hash_password(password):
    """Hashes a password using SHA-256. Returns a 32-byte binary hash"""
    return hashlib.sha256(password.encode()).digest()

"""
Methods for encoding.
"""
def encode_string(s):
    """Encodes a string with a 1-byte length prefix."""
    encoded = s.encode('utf-8')
    return struct.pack(f"B{len(encoded)}s", len(encoded), encoded) # s represents string type

def encode_string_array(strings):
    """Encodes an array of strings with a length prefix."""
    encoded_strings = b''.join(encode_string(s) for s in strings)
    return struct.pack("!B", len(strings)) + encoded_strings

def encode_message(msg_type, payload):
    """Encodes a binary message with a header and payload.

    Parameters
    * msg_type: MESSAGE_TYPES, specifying the request type
    """
    payload_size = len(payload)
    header = struct.pack("!BH", msg_type, payload_size) # H represents short, which is the type of payload_size
    return header + payload

"""
Methods for decoding.
"""
def decode_string(data, offset):
    """Decodes a length-prefixed string from binary data."""
    length = struct.unpack_from("B", data, offset)[0]  # Read length
    offset += 1
    value = struct.unpack_from(f"{length}s", data, offset)[0].decode("utf-8")
    return value, offset + length

def decode_string_array(data):
    """Decodes an array of length-prefixed strings."""
    offset = 0
    num_strings = struct.unpack_from("!B", data, offset)[0]  # Read count
    offset += 1

    strings = []
    for _ in range(num_strings):
        s, offset = decode_string(data, offset)
        strings.append(s)

    return strings

"""
Methods for creating requests.
"""
def create_account(username, password):
    """Encodes a Create Account request."""
    timestamp = int(time.time())
    hashed_password = hash_password(password)

    payload = encode_string(username) + hashed_password + struct.pack("!I", timestamp)
    return encode_message(MESSAGE_TYPES["CREATE_ACCOUNT"], payload)

def login(username, password):
    """Encodes a Login request."""
    timestamp = int(time.time())
    hashed_password = hash_password(password)

    payload = encode_string(username) + hashed_password + struct.pack("!I", timestamp)
    return encode_message(MESSAGE_TYPES["LOGIN"], payload)

def send_message(sender, receiver, message):
    """Encodes a Send Message request."""
    timestamp = int(time.time())
    payload = encode_string(sender) + encode_string(receiver) + encode_string(message) + struct.pack("!I", timestamp)
    return encode_message(MESSAGE_TYPES["SEND_MESSAGE"], payload)

def read_message(username, limit=10):
    """Encodes a Read Message request."""
    timestamp = int(time.time())
    payload = encode_string(username) + struct.pack("!I", limit) + struct.pack("!I", timestamp)
    return encode_message(MESSAGE_TYPES["READ_MESSAGE"], payload)

def delete_message(username, message_ids, timestamp):
    """Encodes a Delete Message request."""
    timestamp = int(time.time())
    payload = encode_string(username) + encode_string_array(message_ids) + struct.pack("!I", timestamp)
    return encode_message(MESSAGE_TYPES["DELETE_MESSAGE"], payload)

def delete_account(username, password, timestamp):
    """Encodes a Delete Account request."""
    timestamp = int(time.time())
    hashed_password = hash_password(password)

    payload = encode_string(username) + hashed_password + struct.pack("!I", timestamp)
    return encode_message(MESSAGE_TYPES["DELETE_MESSAGE"], payload)
