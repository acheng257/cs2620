import subprocess

num_clients = 5  # Number of client instances
clients = []

for _ in range(num_clients):
    p = subprocess.Popen(["python", "client.py"])
    clients.append(p)

# Wait for all clients to complete
for p in clients:
    p.wait()
