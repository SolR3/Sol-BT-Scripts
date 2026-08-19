# Standard imports
import time

# Local imports
from .checker_base import ValidatorChecker
from .constants import RED_X
from .utils import send_monitor_notification


class ValidatorCheckerSystemMemory(ValidatorChecker):
    log_prefix = "CHECK SYSTEM MEMORY"

    def _init_setup(self, options):    
        # Set restart threshold
        self._restart_threshold = options.mem_threshold

    def _run(self):
        try:
            import psutil
        except ImportError:
            self.log_error("Could not import the psutil python module. Not checking for high system memory.")
            send_monitor_notification(
                self.log_prefix,
                f"{RED_X} Failed to run system memory checker on subnet {self._netuid}. No psutil module."
            )
            return

        self.log_info("")
        self.log_info("Checking for high system memory.")
        self.log_info("")

        while True:
            memory_used = psutil.virtual_memory().percent
            self.log_info(f"System memory usage is {memory_used}%.")

            if memory_used >= self._restart_threshold:
                self.log_info(f"{memory_used}% memory usage >= {self._restart_threshold}%.")
                self._restart_validator(f"System memory usage is {memory_used}%.")
            else:
                self.log_info(f"{memory_used}% memory usage < {self._restart_threshold}%.")
                self.log_info("Doing nothing.")

            sleep_interval = 600  # 10 minutes
            self.log_info(f"Sleeping for {sleep_interval} seconds.")
            time.sleep(sleep_interval)
