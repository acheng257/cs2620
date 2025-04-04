import random
import time
import queue
import os
from .network import start_server, send_message


class Machine:
    """
    A class representing a machine in a distributed system implementing a logical clock.

    This class manages message passing between machines, maintains a logical clock,
    and logs events (internal, send, receive) with both system time and logical clock values.

    Attributes:
        id (int): Unique identifier for the machine
        host (str): Host address the machine runs on
        port (int): Port number the machine listens on
        neighbors (list): List of (host, port) tuples representing neighbor machines
        clock (int): Current value of the logical clock
        clock_rate (int): Random rate (1-6) at which the machine's clock ticks
        running (bool): Flag indicating if the machine is running
        message_queue (Queue): Queue for storing incoming messages
        log_file (file): File handle for logging events
        internal_work_probability (float): Probability between 0-1 that machine performs internal work.
    """

    def __init__(
        self,
        id,
        host,
        port,
        neighbors,
        clock_rate_range=(1, 6),
        internal_work_probability=0.7,
    ):
        self.id = id
        self.host = host
        self.port = port
        self.neighbors = neighbors
        # Configure clock rate based on provided range.
        self.clock_rate = random.randint(clock_rate_range[0], clock_rate_range[1])
        self.internal_work_probability = internal_work_probability
        self.clock = 0
        self.running = True
        self.message_queue = queue.Queue()
        log_path = os.path.join("logs", f"machine_{self.id}.log")
        self.log_file = open(log_path, "w")

        self.log_event("INIT", f"Clock rate initialized as {self.clock_rate}")

    def handle_incoming_message(self, message):
        """
        Handle an incoming message by adding it to the message queue.

        Args:
            message (str): The received message to be queued
        """
        self.message_queue.put(message)
        print(f"Machine {self.id} received message: {message}")

    def start_network(self):
        """
        Start the network server for this machine.

        Initializes a TCP server socket that listens for incoming connections
        and handles incoming messages.
        """
        self.server_socket = start_server(
            self.host, self.port, self.handle_incoming_message
        )

    def receive_message(self, sender_id, sender_timestamp, msg):
        """
        Process a received message and update the logical clock.

        Args:
            sender_id (int): ID of the sending machine
            sender_timestamp (int): Logical clock value of the sender
            msg (str): Content of the message

        Returns:
            bool: True if message was processed successfully
        """
        self.clock = max(self.clock, sender_timestamp) + 1

        self.log_event(
            event_type="RECEIVE", detail=f"Received from M{sender_id}: {msg}"
        )
        return True

    def send_message(self, target_peer, message):
        """
        Send a message to one or more target peers and update the logical clock.

        Args:
            target_peer (list): List of (host, port) tuples for target machines
            message (str): Message to be sent
        """
        for target in target_peer:
            send_message(target[0], target[1], message)

        self.log_event(
            event_type="SEND", detail=f"Sending message to {target_peer}: {message}."
        )

        self.clock += 1

    def log_event(self, event_type, detail):
        """
        Log an event with system time, machine ID, logical clock, and event details.

        Args:
            event_type (str): Type of event (INTERNAL, SEND, or RECEIVE)
            detail (str): Detailed description of the event
        """
        current_time = time.time()  # real (system) time
        log_line = (
            f"[SystemTime={current_time:.3f}] "
            f"[Machine={self.id}] "
            f"[LogicalClock={self.clock}] "
            f"[Event={event_type}] {detail}\n"
        )
        self.log_file.write(log_line)
        self.log_file.flush()
        print(log_line)

    def main_loop(self):
        start_time = time.time()
        time_per_tick = 1.0 / self.clock_rate
        while self.running:
            if time.time() - start_time >= 60:  # run for 60 seconds
                self.running = False
                break

            time.sleep(time_per_tick)
            if not self.message_queue.empty():
                message = self.message_queue.get()
                try:
                    sender_id, sender_timestamp, msg = message.split("|")
                    sender_timestamp = int(sender_timestamp)
                    self.clock = max(self.clock, sender_timestamp) + 1
                    queue_length = self.message_queue.qsize()
                    self.log_event(
                        "RECEIVE",
                        f"Received from M{sender_id}: {msg}, Queue length now: {queue_length}",
                    )
                except Exception as e:
                    print(f"Error parsing message: {message} : {e}")
                    continue
            else:
                # Use the configured probability to decide on internal work.
                if random.random() < self.internal_work_probability:
                    self.clock += 1
                    self.log_event("INTERNAL", "Doing internal work.")
                else:
                    # Otherwise, perform message sending. Here we simplify the logic:
                    # Choose a random neighbor or send to all based on some random decision.
                    action = random.randint(1, 3)
                    if action == 1 and self.neighbors:
                        target = self.neighbors[0]
                        msg = f"{self.id}|{self.clock}|Hello from M{self.id}"
                        self.send_message([target], msg)
                    elif action == 2 and len(self.neighbors) > 1:
                        target = self.neighbors[1]
                        msg = f"{self.id}|{self.clock}|Hello from M{self.id}"
                        self.send_message([target], msg)
                    elif action == 3:
                        msg = f"{self.id}|{self.clock}|Hello from M{self.id}"
                        self.send_message(self.neighbors, msg)

    def run(self):
        """
        Start the machine's operation.

        Initializes the network server and enters the main processing loop.
        The machine will run for 60 seconds before shutting down.
        """
        self.start_network()
        self.main_loop()
