"""Cooperative bounds checked during long calls on the main Python thread."""

import signal
import threading
from contextlib import contextmanager

from .contract import RegionalError


@contextmanager
def resource_monitor(job):
    if threading.current_thread() is not threading.main_thread():
        raise RegionalError(
            "Regional execution requires the main thread for resource monitoring"
        )
    previous = signal.getsignal(signal.SIGALRM)
    timer = signal.getitimer(signal.ITIMER_REAL)
    if timer != (0.0, 0.0):
        raise RegionalError("Regional execution refuses an existing process alarm")

    def check(signum, frame):
        job.guard()

    signal.signal(signal.SIGALRM, check)
    signal.setitimer(signal.ITIMER_REAL, 0.5, 0.5)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
