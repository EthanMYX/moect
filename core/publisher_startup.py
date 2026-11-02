"""Bounded UI startup recovery, independent of publication/network jobs."""
import threading
import time


class StartupGuard:
    def __init__(self, timeout=18, max_retries=1, clock=time.monotonic):
        self.clock = clock
        self.timeout = timeout
        self.max_retries = max_retries
        self.lock = threading.RLock()
        self.generation = 0
        self.retries = 0
        self.is_ready = False
        self.failed = False
        self.reason = ''
        self.deadline = clock() + timeout

    def begin_document(self):
        with self.lock:
            self.generation += 1
            self.is_ready = False
            self.failed = False
            self.deadline = self.clock() + self.timeout

    def mark_ready(self, generation):
        with self.lock:
            if type(generation) is not int or generation != self.generation:
                return False
            self.is_ready = True
            self.failed = False
            self.reason = ''
            return True

    def fail(self, reason, generation=None):
        with self.lock:
            if generation is not None and generation != self.generation:
                return
            self.is_ready = False
            self.reason = reason
            self.deadline = self.clock()

    def manual_retry(self):
        with self.lock:
            self.retries = 0
            self.reason = ''
            self.begin_document()

    def tick(self):
        with self.lock:
            if self.is_ready or self.failed or self.clock() < self.deadline:
                return None
            if self.retries < self.max_retries:
                self.retries += 1
                self.begin_document()
                return 'reload'
            self.failed = True
            return 'failed'
