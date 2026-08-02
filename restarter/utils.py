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
from .constants import DISCORD_MONITOR_URL


_pm2_log_output_wait_timer = None
restart_lock = threading.Lock()


def get_pm2_log_output_wait_timer():
    return _pm2_log_output_wait_timer


def set_pm2_log_output_wait_timer(pm2_log_output_wait_timer):
    global _pm2_log_output_wait_timer
    _pm2_log_output_wait_timer = pm2_log_output_wait_timer


def send_monitor_notification(log_prefix, message):
    payload = json.dumps({"content": f"validator restarter: {message}"})
    monitor_cmd = [
        "curl", "-H", "Content-Type: application/json",
        "-d", payload, DISCORD_MONITOR_URL
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
