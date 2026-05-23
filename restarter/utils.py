# Standard imports
import json
import shlex
import subprocess
import threading

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
    bittensor.logging.info(f"{log_prefix}: Running command: '{monitor_cmd_str}'")

    try:
        subprocess.run(monitor_cmd, check=True)
    except subprocess.CalledProcessError as exc:
        bittensor.logging.error(f"{log_prefix}: Failed to send discord monitor notification.")
        bittensor.logging.error(f"{log_prefix}: '{monitor_cmd_str}' command failed with error {exc}")
    else:
        bittensor.logging.info(f"{log_prefix}: Discord monitor notification successfully sent.")
