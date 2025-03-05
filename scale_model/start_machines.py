import subprocess
import sys
import time


def start_machine(machine_id, port, neighbors):
    # Build the command to start a machine.
    # We use sys.executable to ensure we use the same Python interpreter.
    command = [
        sys.executable,
        "main.py",
        "--id",
        str(machine_id),
        "--host",
        "localhost",
        "--port",
        str(port),
        "--neighbors",
        neighbors,
    ]
    print(f"Starting machine {machine_id} on port {port} with neighbors: {neighbors}")
    return subprocess.Popen(command)


def main():
    # Configuration for three machines.
    # For example:
    # Machine 1 listens on port 8000 and has neighbors on ports 8001 and 8002.
    # Machine 2 listens on port 8001 and has neighbors on ports 8000 and 8002.
    # Machine 3 listens on port 8002 and has neighbors on ports 8000 and 8001.
    machines = [
        {"id": 1, "port": 8000, "neighbors": "localhost:8001,localhost:8002"},
        {"id": 2, "port": 8001, "neighbors": "localhost:8000,localhost:8002"},
        {"id": 3, "port": 8002, "neighbors": "localhost:8000,localhost:8001"},
    ]

    processes = []
    for machine in machines:
        p = start_machine(machine["id"], machine["port"], machine["neighbors"])
        processes.append(p)
        # Optionally add a short delay between starting machines
        time.sleep(0.5)

    # Optionally, wait for all processes to complete.
    # In many distributed system simulations, these processes run indefinitely.
    for p in processes:
        p.wait()


if __name__ == "__main__":
    main()
