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
    parser.add_argument(
        "--id", type=int, required=True, help="Machine identifier (e.g., 1)"
    )
    parser.add_argument(
        "--host", type=str, default="localhost", help="Host to bind the server"
    )
    parser.add_argument(
        "--port", type=int, required=True, help="Port to bind the server"
    )
    parser.add_argument(
        "--neighbors",
        type=str,
        default="",
        help="Comma-separated list of neighbor endpoints (e.g., localhost:8766,localhost:8767)",
    )
    args = parser.parse_args()

    neighbors = parse_neighbors(args.neighbors)
    machine = Machine(args.id, args.host, args.port, neighbors)
    machine.run()


if __name__ == "__main__":
    main()
