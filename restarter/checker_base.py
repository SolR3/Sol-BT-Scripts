# Standard imports
import os
import subprocess
import tempfile

# Bittensor import
import bittensor

# Local imports
from .constants import RED_QM, RED_X
from .utils import (
    get_pm2_log_output_wait_timer,
    restart_lock,
    send_monitor_notification,
)


class ValidatorChecker:
    def __init__(self, options):
        self._netuid = options.netuid
        self._discord_notify = options.discord_notify

        try:
            self._init_restart_stuff(options)
            self._init_setup(options)
            self._run()

        except Exception as err:
            import traceback
            traceback.print_exc()
            self._log_error(f"Error: {err}")

            send_monitor_notification(
                self.log_prefix,
                f"{RED_X} restarter check \"{self.log_prefix}\" "
                f"failed on subnet {self._netuid}"
            )

    @classmethod
    def _log_info(cls, message):
        bittensor.logging.info(f"{cls.log_prefix}: {message}")

    @classmethod
    def _log_error(cls, message):
        bittensor.logging.error(f"{cls.log_prefix}: {message}")

    @classmethod
    def _log_warning(cls, message):
        bittensor.logging.warning(f"{cls.log_prefix}: {message}")

    @classmethod
    def _log_debug(cls, message):
        bittensor.logging.debug(f"{cls.log_prefix}: {message}")

    def _init_setup(self, options):
        raise NotImplementedError("Must be implemented in subclasses.")

    def _run(self):
        raise NotImplementedError("Must be implemented in subclasses.")

    def _init_restart_stuff(self, options):
        self._restart_script =  os.path.expanduser(options.restart_script)
        self._restart_venv = (
            os.path.expanduser(options.restart_venv)
            if options.restart_venv else None)

        self._restart_dir = os.path.expanduser(
            f"~/restart_scripts_sn{options.netuid}")
        os.makedirs(self._restart_dir, exist_ok=True)

        for restart_file in os.listdir(self._restart_dir):
            restart_file_path = os.path.join(self._restart_dir, restart_file)
            if os.path.isfile(restart_file_path):
                os.unlink(restart_file_path)

    def _restart_validator(self, description, force_notify=False):
        # If the restart_lock is currently acquired then another thread is
        # currently running a restart so just return.
        # Otherwise aquire the restart_lock and run a restart.
        if restart_lock.locked():
            self._log_info(f"Subnet {self._netuid} is currently restarting. "
                           f"Skipping retart for: {description}.")
            return

        with restart_lock:
            pm2_log_output_wait_timer = get_pm2_log_output_wait_timer()
            if pm2_log_output_wait_timer:
                pm2_log_output_wait_timer.start_wait_timer()
            self._do_restart(description, force_notify)

    def _do_restart(self, description, force_notify):
        self._log_info(f"Restarting subnet {self._netuid}: {description}.")
        self._log_info(f"Running script: {self._restart_script}")

        if self._restart_venv:
            self._log_info(f"Running in venv: {self._restart_venv}")

            fd, restart_script = tempfile.mkstemp(dir=self._restart_dir,
                prefix = f"restart_{self._netuid}_", suffix=".sh")
            os.close(fd)
            os.chmod(restart_script, 0o700)

            self._log_info(f"Packaging venv and script into {restart_script}")
            with open(restart_script, "w") as fd:
                venv_activate = os.path.join(self._restart_venv, "bin/activate")
                fd.write("#!/bin/bash\n"
                            "\n"
                            "deactivate\n"
                            f"source {venv_activate}\n"
                            f"{self._restart_script}\n")
            restart_cmd = [restart_script]

        else:
            restart_cmd = [self._restart_script]
            restart_script = None

        restart_cmd_str = " ".join(restart_cmd)
        self._log_info(f"Running command: '{restart_cmd_str}'")

        try:
            subprocess.run(restart_cmd, check=True)

        except subprocess.CalledProcessError as exc:
            self._log_error(
                f"'{restart_cmd_str}' command failed with error: {exc}")
            self._send_restart_monitor_notification(
                f"{RED_QM} Possibly failed to restart subnet {self._netuid} - {description}",
                force_notify
            )
            return False

        finally:
            if restart_script:
                os.unlink(restart_script)

        self._log_info(f"Subnet '{self._netuid}' successfully restarted.")
        self._send_restart_monitor_notification(
            f"Successfully restarted on subnet {self._netuid} - {description}",
            force_notify
        )

        return True

    def _send_restart_monitor_notification(self, message, force_notify):
        if not force_notify and not self._discord_notify:
            self._log_info("Not sending discord monitor notification.")
            return

        send_monitor_notification(self.log_prefix, message)
