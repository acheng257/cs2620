import re
import sys
import pandas as pd
import matplotlib.pyplot as plt

def parse_log_line(line):
    """
    Parses a log line and returns a dictionary with:
      - system_time (float)
      - machine (int)
      - logical_clock (int)
      - event (string)
      - detail (string)
      - queue_length (int or None)
    """
    pattern = r"\[SystemTime=([\d\.]+)\]\s+\[Machine=(\d+)\]\s+\[LogicalClock=(\d+)\]\s+\[Event=([A-Z]+)\]\s+(.*)"
    match = re.match(pattern, line)
    if match:
        system_time = float(match.group(1))
        machine = int(match.group(2))
        logical_clock = int(match.group(3))
        event = match.group(4)
        detail = match.group(5)

        queue_length = None
        q_match = re.search(r"Queue length now:\s*(\d+)", detail)
        if q_match:
            queue_length = int(q_match.group(1))
        return {
            "system_time": system_time,
            "machine": machine,
            "logical_clock": logical_clock,
            "event": event,
            "detail": detail,
            "queue_length": queue_length
        }
    return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python plot_logs.py <log_file>")
        sys.exit(1)

    log_file = sys.argv[1]
    records = []
    
    with open(log_file, "r") as f:
        for line in f:
            parsed = parse_log_line(line)
            if parsed:
                records.append(parsed)
    
    if not records:
        print("No valid log entries found.")
        sys.exit(1)
    
    df = pd.DataFrame(records)
    
    machines = df["machine"].unique()
    
    fig, axs = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
    
    # Plot Logical Clock vs. System Time for each machine
    for m in machines:
        df_m = df[df["machine"] == m]
        axs[0].plot(df_m["system_time"], df_m["logical_clock"], marker='o', label=f"Machine {m}")
    axs[0].set_ylabel("Logical Clock")
    axs[0].set_title("Logical Clock vs. System Time")
    axs[0].legend()
    
    # Plot Message Queue Length vs. System Time (only for lines where queue length was logged)
    df_queue = df[df["queue_length"].notnull()]
    for m in machines:
        df_q = df_queue[df_queue["machine"] == m]
        if not df_q.empty:
            axs[1].plot(df_q["system_time"], df_q["queue_length"], marker='x', label=f"Machine {m}")
    axs[1].set_xlabel("System Time")
    axs[1].set_ylabel("Queue Length")
    axs[1].set_title("Message Queue Length vs. System Time")
    axs[1].legend()
    
    plt.tight_layout()
    
    machine_name = log_file.split('.')[0]
    output_filename = f"plots/{machine_name}_plots.png"
    plt.savefig(output_filename)
    print(f"Plots saved as {output_filename}")
    
    plt.show()

if __name__ == "__main__":
    main()
