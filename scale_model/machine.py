import random
import time
import queue
from network import start_server, send_message


class Machine:
    def __init__(self, id, host, port, neighbors):
        self.id = id  # machine identifier
        self.host = host
        self.port = port
        self.neighbors = neighbors
        self.clock = 0
        self.clock_rate = random.randint(1, 6)
        self.running = True
        self.message_queue = queue.Queue()
        self.log_file = open(f"machine_{self.id}.log", "w")

    def handle_incoming_message(self, message):
        self.message_queue.put(message)
        print(f"Machine {self.id} received message: {message}")

    def start_network(self):
        self.server_socket = start_server(
            self.host, self.port, self.handle_incoming_message
        )

    def receive_message(self, sender_id, sender_timestamp, msg):
        self.clock = max(self.clock, sender_timestamp) + 1

        self.log_event(
            event_type="RECEIVE", detail=f"Received from M{sender_id}: {msg}"
        )
        return True

    def send_message(self, target_peer, message):
        send_message(target_peer[0], target_peer[1], message)
        self.clock += 1
        self.log_event(
            event_type="SEND", detail=f"Sending message to {target_peer}: {message}."
        )

    def log_event(self, event_type, detail):
        """
        Simple text logging to our dedicated file.
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
        time_per_tick = 1.0 / self.clock_rate
        while self.running:
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
                next_action = random.randint(1, 10)
                if next_action == 1:
                    if self.neighbors:
                        target = self.neighbors[0]
                        msg = f"{self.id}|{self.clock}|Hello from M{self.id}"
                        self.send_message(target, msg)
                elif next_action == 2:
                    if len(self.neighbors) > 1:
                        target = self.neighbors[1]
                        msg = f"{self.id}|{self.clock}|Hello from M{self.id}"
                        self.send_message(target, msg)
                elif next_action == 3:
                    for neighbor in self.neighbors:
                        msg = f"{self.id}|{self.clock}|Hello from M{self.id}"
                        self.send_message(neighbor, msg)
                else:
                    self.clock += 1
                    self.log_event(event_type="INTERNAL", detail="Doing internal work.")

    def run(self):
        """
        Starts the network server and enters the main loop.
        """
        self.start_network()
        self.main_loop()
