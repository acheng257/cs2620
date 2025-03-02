import random
import time

class Machine:
    def __init__(self, id, host, port):
        self.id = id # machine identifier
        self.host = host
        self.port = port
        self.clock = 0
        self.clock_rate = random.randint(1, 6)
        self.running = False
        self.message_queue = []

    def receive_message(self, sender_id, sender_timestamp, msg):
        self.clock = max(self.clock, sender_timestamp) + 1

        self.log_event(
            event_type="RECEIVE",
            detail=f"Received from M{sender_id}: {msg}"
        )
        return True
    
    def send_message(self, target_ids, msg):
        self.clock += 1

        for target_id in target_ids:
            self.log_event(
                event_type="SEND",
                detail=f"Sending message to {target_id}: {msg}."
            )

            # TODO: send the message

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
        
    def main_loop(self):
        while self.running:
            time_per_tick = 1.0 / self.ticks_per_second
            time.sleep(time_per_tick)

            if self.message_queue:
                # self.receive_message()
                pass
            else:
                next_action = random.randint(1, 10)
                if next_action == 1:
                    # target = random.choice(self.neighbors)
                    target = self.neighbors[0]
                    self.send_message([target], "Hello from M{}".format(self.machine_id))
                elif next_action == 2:
                    target = self.neighbors[1]
                    self.send_message([target], "Hello from M{}".format(self.machine_id))
                elif next_action == 3:
                    self.send_message([self.neighbors[0], self.neighbors[1]], 
                                      "Hello from M{}".format(self.machine_id))
                else:
                    self.logical_clock += 1
                    self.log_event(
                        event_type="INTERNAL",
                        detail=f"Doing internal work."
                    )

    