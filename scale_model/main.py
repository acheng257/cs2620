import argparse
from src.machine import Machine

def parse_neighbors(neighbor_str):
    """
    Parses a comma-separated list of neighbor endpoints in the format host:port
    into a list of (host, port) tuples.
    """
    neighbors = []
    if neighbor_str:
        for entry in neighbor_str.split(","):
            parts = entry.split(":")
            if len(parts) == 2:
                host = parts[0]
                try:
                    port = int(parts[1])
                except ValueError:
                    continue
                neighbors.append((host, port))
    return neighbors

def main():
    parser = argparse.ArgumentParser(description="Distributed Machine Node")
    parser.add_argument("--id", type=int, required=True, help="Machine identifier (e.g., 1)")
    parser.add_argument("--host", type=str, default="localhost", help="Host to bind the server")
    parser.add_argument("--port", type=int, required=True, help="Port to bind the server")
    parser.add_argument(
        "--neighbors",
        type=str,
        default="",
        help="Comma-separated list of neighbor endpoints (e.g., localhost:8766,localhost:8767)"
    )
    # New configurable parameters
    parser.add_argument("--clock_rate_min", type=int, default=1, help="Minimum clock rate")
    parser.add_argument("--clock_rate_max", type=int, default=6, help="Maximum clock rate")
    parser.add_argument("--internal_work_prob", type=float, default=0.4, help="Probability of performing internal work")
    
    args = parser.parse_args()

    neighbors = parse_neighbors(args.neighbors)
    
    # Pass the new parameters to the Machine constructor.
    machine = Machine(
        args.id,
        args.host,
        args.port,
        neighbors,
        clock_rate_range=(args.clock_rate_min, args.clock_rate_max),
        internal_work_probability=args.internal_work_prob
    )
    machine.run()

if __name__ == "__main__":
    main()
