# start_machines.py
import subprocess
import sys
import argparse

def start_machine(machine_id, port, neighbors, clock_rate_min, clock_rate_max, internal_work_prob):
    # Build the command to start a machine.
    command = [
        sys.executable,
        "main.py",
        "--id", str(machine_id),
        "--host", "localhost",
        "--port", str(port),
        "--neighbors", neighbors,
        "--clock_rate_min", str(clock_rate_min),
        "--clock_rate_max", str(clock_rate_max),
        "--internal_work_prob", str(internal_work_prob)
    ]
    print(f"Starting machine {machine_id} on port {port} with neighbors: {neighbors}")
    return subprocess.Popen(command)

def main():
    parser = argparse.ArgumentParser(description="Start distributed machines with configurable parameters.")
    parser.add_argument("--clock_rate_min", type=int, default=1, help="Minimum value for the machine’s random clock rate.")
    parser.add_argument("--clock_rate_max", type=int, default=6, help="Maximum value for the machine’s random clock rate.")
    parser.add_argument("--internal_work_prob", type=float, default=0.4, help="Probability of performing internal work (0-1).")
    args = parser.parse_args()

    # Configuration for three machines.
    machines = [
        {"id": 1, "port": 8000, "neighbors": "localhost:8001,localhost:8002"},
        {"id": 2, "port": 8001, "neighbors": "localhost:8000,localhost:8002"},
        {"id": 3, "port": 8002, "neighbors": "localhost:8000,localhost:8001"},
    ]

    processes = []
    for machine in machines:
        p = start_machine(
            machine["id"],
            machine["port"],
            machine["neighbors"],
            args.clock_rate_min,
            args.clock_rate_max,
            args.internal_work_prob
        )
        processes.append(p)
        
    # Wait for all machine processes to complete.
    for p in processes:
        p.wait()

if __name__ == "__main__":
    main()
