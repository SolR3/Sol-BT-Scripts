# Standard imports
import json
import logging
import shlex
import subprocess
import sys
import threading
import time

# Bittensor import
import bittensor

# Local imports
from .constants import (
    DISCORD_MONITOR_URL,
    DISCORD_MONITOR_GIT_REPO_URL,
)


class WaitTimer:
    def __init__(self, wait_time):
        self._timer_lock = threading.Lock()
        self._wait_timer = None
        self._wait_event = threading.Event()
        self._wait_time = wait_time
        self._start_time = 0

    def get_waiting_status(self):
        if self._wait_event.is_set():
            return max(0, self._wait_time - (time.monotonic() - self._start_time))
        return 0

    def start_wait_timer(self):
        with self._timer_lock:
            self._start_time = time.monotonic()
            self._wait_event.set()
            if self._wait_timer:
                self._wait_timer.cancel()
            self._wait_timer = threading.Timer(
                interval=self._wait_time, function=self._unset_wait_event
            )
            self._wait_timer.start()
            self._log_wait_timer_started()

    def _unset_wait_event(self):
        with self._timer_lock:
            self._wait_event.clear()
            self._log_wait_timer_finished()

    def _log_wait_timer_started(self):
        raise NotImplementedError

    def _log_wait_timer_finished(self):
            raise NotImplementedError


class _RestartWaitTimers:
    def __init__(self):
        self._wait_timers = {}

    def get_wait_timers(self):
        return self._wait_timers.values()

    def get_wait_timer(self, checker_cls):
        return self._wait_timers.get(checker_cls)

    def set_wait_timer(self, checker_cls, wait_timer):
        self._wait_timers[checker_cls] = wait_timer


restart_wait_timers = _RestartWaitTimers()
restart_lock = threading.Lock()


def send_monitor_notification(log_prefix, message, git_update_notify=False):
    discord_monitor_url = (
        DISCORD_MONITOR_GIT_REPO_URL if git_update_notify else DISCORD_MONITOR_URL
    )
    payload = json.dumps({"content": f"validator restarter: {message}"})
    monitor_cmd = [
        "curl", "-H", "Content-Type: application/json",
        "-d", payload, discord_monitor_url
    ]

    monitor_cmd_str = shlex.join(monitor_cmd)
    logger.info(f"{log_prefix}: Running command: '{monitor_cmd_str}'")

    try:
        subprocess.run(monitor_cmd, check=True)
    except subprocess.CalledProcessError as exc:
        logger.error(f"{log_prefix}: Failed to send discord monitor notification.")
        logger.error(f"{log_prefix}: '{monitor_cmd_str}' command failed with error {exc}")
    else:
        logger.info(f"{log_prefix}: Discord monitor notification successfully sent.")


def _get_logger():
    # bittensor <= 10
    if hasattr(bittensor, "logging"):
        return bittensor.logging

    # bittensor >= 11
    class Logger:
        class BtDateFormatter(logging.Formatter):
            def formatTime(self, record, datefmt=None):
                created = self.converter(record.created)
                if datefmt:
                    s = time.strftime(datefmt, created)
                else:
                    s = time.strftime("%Y-%m-%d %H:%M:%S", created)
                s += f".{int(record.msecs):03d}"
                return s

        def __init__(self):
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(Logger.BtDateFormatter("%(asctime)s | %(levelname)s | %(message)s"))

            self._logger = logging.getLogger("bittensor")
            self._logger.addHandler(handler)
            self._logger.propagate = False

        def __getattr__(self, name):
            if name == "_logger":
                raise AttributeError(name)
            return getattr(self._logger, name)

        def enable_debug(self):
            self._logger.setLevel(logging.DEBUG)

        def enable_info(self):
            self._logger.setLevel(logging.INFO)

    return Logger()


logger = _get_logger()
