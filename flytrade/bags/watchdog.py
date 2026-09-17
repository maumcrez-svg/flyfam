"""Detect a stuck round clock without opening another database connection."""
import faulthandler
import os
import sys
import threading
import time


class RoundWatchdog:
    def __init__(self, *, timeout=30, interval=2, clock=time.monotonic, terminate=os._exit):
        self.timeout = timeout
        self.interval = interval
        self.clock = clock
        self.terminate = terminate
        self.last_progress = clock()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, name='bag-round-watchdog', daemon=True)

    def start(self):
        self.thread.start()

    def progress(self):
        # Call only AFTER tick's durable transaction has committed.
        self.last_progress = self.clock()

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=self.interval + .5)

    def _run(self):
        while not self.stopped.wait(self.interval):
            if self.clock() - self.last_progress < self.timeout:
                continue
            print(f'[bag-watchdog] No committed round tick for {self.timeout:g} seconds; '
                  'dumping threads and exiting for service recovery.', file=sys.stderr, flush=True)
            try:
                faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            except (OSError, ValueError):
                pass
            self.terminate(70)
            return
