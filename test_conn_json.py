import subprocess
import time

num_clients = 5  # Number of client instances
clients = []

for _ in range(num_clients):
    p = subprocess.Popen(["python", "clients/json_client.py"])
    clients.append(p)
    time.sleep(0.5)

# Wait for all clients to complete
for p in clients:
    p.wait()
