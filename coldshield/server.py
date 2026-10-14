"""Bounded TCP workers for the loopback-only laboratory."""
import socketserver
import threading


class LabServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    # Retain the runtime lease until all bounded handlers finish on shutdown.
    daemon_threads = False
    block_on_close = True

    def __init__(self, port, handler):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(("127.0.0.1", port), handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()
