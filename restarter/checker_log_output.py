# Standard imports
import os
import pty
import re
import subprocess
import threading
import time


# Local imports
from .checker_base import ValidatorChecker
from .constants import RED_EP
from .utils import (
    get_pm2_log_output_wait_timer,
    set_pm2_log_output_wait_timer,
    send_monitor_notification,
)


class ValidatorCheckerLogOutputFactory(ValidatorChecker):
    log_prefix = "CHECK LOG OUTPUT"

    def __new__(cls, options):
        if cls is not ValidatorCheckerLogOutputFactory:
            return super().__new__(cls)

        netuid = options.netuid
        log_checker_type = options.log_checker_type

        class_base = f"ValidatorChecker{log_checker_type}LogOutput"
        class_netuid = f"{class_base}Sn{netuid}"

        class_netuid_obj = globals().get(class_netuid)
        if class_netuid_obj:
            cls.log_info(f"Running log output checker class: {class_netuid}")
            return super().__new__(class_netuid_obj)

        cls.log_info(f"Running log output checker class: {class_base}")
        class_base_obj = globals()[class_base]
        return super().__new__(class_base_obj)


class ValidatorCheckerLogOutput(ValidatorCheckerLogOutputFactory):

    def _init_setup(self, options, process_name):
        self._do_check_errors = options.do_check_errors
        self._do_check_blacklist = options.do_check_blacklist_logs

        if not self._generic_patterns and not self._subnet_patterns:
            self.log_warning(
                f"No log patterns defined for subnet {self._netuid}. "
                "Not checking for restart patterns."
            )
            self._do_check_errors = False

        # Ignore any lines longer than this as it can be safely assumed that any log lines longer
        # than this that contain blacklist patterns are just verbose logs of code/text/etc. that
        # just happen to contain the word "blacklist" in them. This is easier than trying to
        # determine an exclude pattern for these verbose logs.
        self._blacklist_log_max_length = 500

        self._blacklist_regexes = [
            re.compile(match_string, flags=flags) for match_string, flags in (
                (r"blacklist", re.IGNORECASE),
                (r"403.+Forbidden", 0),  # re.NOFLAG doesn't exist in python 3.10
            )
        ]
        self._blacklist_exclude_search_regexes = [
            re.compile(exclude_string) for exclude_string in (
                r"reconnect_blacklist pruned",  # sn2
                r"UnknownSynapseError",  # sn7, sn74, sn128
                r"blacklist_fn took",  # sn8
                r"Set dynamic config",  # sn12: setting some BLACKLIST-related env var
                r"Evicting expired miner blacklists",   # sn12
                r"reddit\.com",  # sn13
                r"tweet_id=",  # sn13
                r"Judge response unparseable",  # sn15
                r"validator\.api\.registry_blacklist",  # sn19: module for blacklisting miners
                r"validator\.verification\.blacklist",  # sn19: module for blacklisting miners
                r"twitter_content_relevance",  # sn22: contains twitter content which could have the word "blacklist" in it
                r"Failed to decode JSON object",  # sn22: contains twitter content which could have the word "blacklist" in it
                r"Verdict:",  # sn22: more twitter stuff
                r"(GET|POST) /blacklist-xxx HTTP/1\.1",  # sn34
                r"/plugins/spamx/BlackList\.Examine\.class\.php",  # sn34, sn67
                r"https://api\.almanac\.market/api/v1/trading/trading-history",  # sn41
                r"loaded \d+ blacklisted hotkeys",  # sn44
                r"https://photon\.komoot\.io",  # sn54
                r"tensorauth\.qbittensorlabs\.com/token",  # sn63
                r"Found \d+ blacklisted miners to exclude",  # sn64
                r"session_id=",  # sn67: scraping something off internet that happens to have "blacklist" in it
                r"tool call completed",  # sn67
                r"Set scores to 0 for blacklisted UIDs",  # sn74
                r"not registered\.",  # sn74
                r"Blacklist fetch failed",  # sn78
                r"Blacklist unavailable",  # sn78
                r"Miner .*is BLACKLISTED",  # sn96
                r"Blacklist check timeout",  # sn96
                r"(GET|POST) /v1/[\w/]+ HTTP/1\.1",  # sn103: seems innocuous
                r"recipient_hotkey=5D7jkdtPJjLv635hUiXFa4cTnZsw7x8CCsd1czj3pk9bz5f7",  # sn103: Kraken's vali hotkey...who knows
                r"https://minos-r2-proxy\.minos-ai\.workers\.dev",  # sn107
                r"Invalid submission for hotkey",  # sn108: blacklisted miners
                r"Got task:",  # sn114
                r"https://platform\.thesoma\.ai/validator/submit_swebench_validation_score",  # sn114
                r"hotkey_not_in_metagraph\.",  # sn128: blacklisted miners
            )
        ]
        self._blacklist_exclude_match_regexes = [
            re.compile(f"^{exclude_string}$") for exclude_string in (
                r"blacklist:",
            )
        ]

        self._blacklist_wait_time = 86400  # 1 day
        self._blacklist_notify_time = None
        self._process_name = process_name

    def _check_for_blacklist(self, log_line):
        current_time = time.time()
        if (
            self._blacklist_notify_time and 
            current_time < (self._blacklist_notify_time + self._blacklist_wait_time)
        ):
            self.log_debug(
                f"({self._process_name}) Log line blacklist check skipped. "
                "Too soon since last notification."
            )
            return

        for blacklist_regex in self._blacklist_regexes:
            if blacklist_regex.search(log_line):
                self.log_info(f"Log line matches a blacklist pattern:\n{log_line}\n")

                if len(log_line) > self._blacklist_log_max_length:
                    self.log_info(
                        f"Log line is longer than {self._blacklist_log_max_length} "
                        "characters. Not sending a discord notification.",
                    )
                    return

                for exclude_regex in self._blacklist_exclude_search_regexes:
                    if exclude_regex.search(log_line):
                        self.log_info(
                            "Log line matches a blacklist exclude pattern. "
                            "Not sending a discord notification."
                        )
                        return

                for exclude_regex in self._blacklist_exclude_match_regexes:
                    if exclude_regex.match(log_line):
                        self.log_info(
                            "Log line matches a blacklist exclude pattern. "
                            "Not sending a discord notification."
                        )
                        return

                self.log_info(
                        "Log line does not match any blacklist exclude patterns. "
                        "Sending a discord notification."
                    )
                send_monitor_notification(
                    self.log_prefix,
                    f"{RED_EP} We're being blacklisted on subnet {self._netuid}"
                )
                self._blacklist_notify_time = current_time
                return


class ValidatorCheckerDockerLogOutput(ValidatorCheckerLogOutput):
    log_prefix = "CHECK DOCKER LOG OUTPUT"
    _generic_patterns = [r"\[Errno 32\] Broken pipe"]
    _subnet_patterns = []

    def _init_setup(self, options):
        super()._init_setup(options, options.docker_container)

        self._docker_container = options.docker_container

    def _run(self):
        self.log_info("")
        self.log_info(f"Checking log output for container: {self._docker_container}.")
        self.log_info("")

        if not self._do_check_errors and not self._do_check_blacklist:
            self.log_warning(
                "Restart patterns and blacklising checks are both False. Nothing to do."
            )
            return

        if self._do_check_errors:
            self.log_info("Checking for errors.")
        if self._do_check_blacklist:
            self.log_info("Checking for miner blacklisting.")

        log_regexes = []
        for log_pattern in self._generic_patterns + self._subnet_patterns:
            log_regexes.append(re.compile(log_pattern))
        command = ["docker", "logs", self._docker_container, "--since", "15s", "--follow"]
        command_str = " ".join(command)

        while True:
            self.log_info(f"Launching process: \"{command_str}\"")

            mfd, sfd = pty.openpty()
            process = subprocess.Popen(
                command, stdout=sfd, stderr=subprocess.STDOUT)
            os.close(sfd)
            master = os.fdopen(mfd)
            while True:
                try:
                    log_line = master.readline()
                except:
                    # The process exited.
                    self.log_info(f"Process exited: \"{command_str}\"")
                    break
                else:
                    if self._do_check_blacklist:
                        # Check if we're being blacklisted
                        self._check_for_blacklist(log_line)

                    if not self._do_check_errors:
                        continue

                    # Check for restart patterns
                    do_restart = False
                    for log_regex in log_regexes:
                        match = log_regex.search(log_line)
                        if match:
                            do_restart = True
                            pattern = match.group()
                            self.log_info(
                                f"Log line matches a restart pattern: \"{pattern}\"\n"
                                f"{log_line}\n")
                            self._restart_validator(
                                f"Docker log output matches a restart pattern: \"{pattern}\""
                            )
                            break
                    if do_restart:
                        break

            self.log_info(f"Killing process: \"{command_str}\"")
            process.kill()
            master.close()
            sleep_time = 60
            self.log_info(f"Sleeping {sleep_time} seconds.")
            time.sleep(sleep_time)


class ValidatorCheckerPm2LogOutput(ValidatorCheckerLogOutput):
    log_prefix = "CHECK PM2 LOG OUTPUT"
    _generic_patterns = [r"\[Errno 32\] Broken pipe"]
    _subnet_patterns = []
    _skip_initial_log_lines = 40

    # Inline wait timer class
    class ErrorLogsWaitTimer:
        def __init__(self, wait_time):
            self._timer_lock = threading.Lock()
            self._wait_timer = None
            self._wait_event = threading.Event()
            self._wait_time = wait_time

        def get_waiting_status(self):
            return self._wait_event.is_set()

        def start_wait_timer(self):
            with self._timer_lock:
                self._wait_event.set()
                if self._wait_timer:
                    self._wait_timer.cancel()
                self._wait_timer = threading.Timer(
                    interval=self._wait_time, function=self._unset_wait_event
                )
                self._wait_timer.start()
                ValidatorCheckerPm2LogOutput.log_info(
                    f"Stopping pm2 log patterns check. Waiting {self._wait_time} "
                    "seconds after restart to continue checking log patterns."
                )

        def _unset_wait_event(self):
            with self._timer_lock:
                self._wait_event.clear()
                ValidatorCheckerPm2LogOutput.log_info(
                    "Continuing pm2 log patterns check."
                )

    def _init_setup(self, options):
        super()._init_setup(options, options.pm2_process)

        self._pm2_process = options.pm2_process
        self._restart_wait_time = options.log_errors_restart_wait_time * 60

    def _run(self):
        self.log_info("")
        self.log_info(f"Checking log output for process: {self._pm2_process}.")
        self.log_info("")

        if not self._do_check_errors and not self._do_check_blacklist:
            self.log_warning(
                "Restart patterns and blacklising checks are both False. Nothing to do."
            )
            return

        if self._do_check_errors:
            self.log_info("Checking for errors.")
        if self._do_check_blacklist:
            self.log_info("Checking for miner blacklisting.")

        self._create_pm2_log_output_wait_timer(self._restart_wait_time)

        log_regexes = []
        for log_pattern in self._generic_patterns + self._subnet_patterns:
            log_regexes.append(re.compile(log_pattern))
        command = ["pm2", "log", self._pm2_process, "--raw"]
        command_str = " ".join(command)

        while True:
            _initial_log_lines = 0
            self.log_info(f"Launching process: \"{command_str}\"")

            mfd, sfd = pty.openpty()
            process = subprocess.Popen(
                command, stdout=sfd, stderr=subprocess.STDOUT)
            os.close(sfd)
            master = os.fdopen(mfd)
            while True:
                try:
                    log_line = master.readline()
                except:
                    # The process exited.
                    self.log_info(f"Process exited: \"{command_str}\"")
                    break
                else:
                    if self._do_check_blacklist:
                        # Check if we're being blacklisted
                        self._check_for_blacklist(log_line)

                    if not self._do_check_errors:
                        continue

                    # Check whether or not restart patterns should be checked
                    if _initial_log_lines < self._skip_initial_log_lines:
                        _initial_log_lines += 1
                        self.log_debug(f"{_initial_log_lines=}")
                        continue
                    elif _initial_log_lines == self._skip_initial_log_lines:
                        _initial_log_lines += 1
                        self.log_info("Starting log patterns check.")

                    if get_pm2_log_output_wait_timer().get_waiting_status():
                        self.log_debug(
                            f"({self._pm2_process}) Log line skipped. "
                            "In waiting mode."
                        )
                        continue

                    # Check for restart patterns
                    for log_regex in log_regexes:
                        match = log_regex.search(log_line)
                        if match:
                            pattern = match.group()
                            self.log_info(
                                f"Log line matches a restart pattern: \"{pattern}\"\n"
                                f"{log_line}\n")
                            self._restart_validator(
                                f"Pm2 log output matches a restart pattern: \"{pattern}\""
                            )
                            break

            self.log_info(f"Killing process: \"{command_str}\"")
            process.kill()
            master.close()
            sleep_time = 15
            self.log_info(f"Sleeping {sleep_time} seconds.")
            time.sleep(sleep_time)

    @classmethod
    def _create_pm2_log_output_wait_timer(cls, wait_time):
        if not get_pm2_log_output_wait_timer():
            pm2_log_output_wait_timer = (
                cls.ErrorLogsWaitTimer(wait_time)
            )
            set_pm2_log_output_wait_timer(pm2_log_output_wait_timer)


class ValidatorCheckerDockerLogOutputSn52(ValidatorCheckerDockerLogOutput):
    _generic_patterns = []
    _subnet_patterns = [r"websockets\.exceptions\.InvalidStatus"]

class ValidatorCheckerDockerLogOutputSn59(ValidatorCheckerDockerLogOutput):
    _subnet_patterns = [r"\[websockets\.client\] unexpected internal error"]

class ValidatorCheckerDockerLogOutputSn64(ValidatorCheckerDockerLogOutput):
    _generic_patterns = []
    _subnet_patterns = []


class ValidatorCheckerPm2LogOutputSn1(ValidatorCheckerPm2LogOutput):
    _subnet_patterns = [r"json\.decoder\.JSONDecodeError:"]

class ValidatorCheckerPm2LogOutputSn4(ValidatorCheckerPm2LogOutput):
    _generic_patterns = []

class ValidatorCheckerPm2LogOutputSn10(ValidatorCheckerPm2LogOutput):
    _subnet_patterns = [r"Error during validation"]

class ValidatorCheckerPm2LogOutputSn16(ValidatorCheckerPm2LogOutput):
    _subnet_patterns = [r"ConnectionRefusedError"]

class ValidatorCheckerPm2LogOutputSn18(ValidatorCheckerPm2LogOutput):
    _subnet_patterns = [r"asyncio\.exceptions\.CancelledError"]

class ValidatorCheckerPm2LogOutputSn21(ValidatorCheckerPm2LogOutput):
    _subnet_patterns = [r"asyncio\.exceptions\.CancelledError"]

class ValidatorCheckerPm2LogOutputSn24(ValidatorCheckerPm2LogOutput):
    _generic_patterns = []

class ValidatorCheckerPm2LogOutputSn27(ValidatorCheckerPm2LogOutput):
    _generic_patterns = []

class ValidatorCheckerPm2LogOutputSn28(ValidatorCheckerPm2LogOutput):
    _subnet_patterns = [r"Transaction has an ancient birth block"]

class ValidatorCheckerPm2LogOutputSn29(ValidatorCheckerPm2LogOutput):
    _generic_patterns = []

class ValidatorCheckerPm2LogOutputSn30(ValidatorCheckerPm2LogOutput):
    _generic_patterns = []

class ValidatorCheckerPm2LogOutputSn32(ValidatorCheckerPm2LogOutput):
    _generic_patterns = []

class ValidatorCheckerPm2LogOutputSn34(ValidatorCheckerPm2LogOutput):
    _subnet_patterns = [
        r"Handshake status 502 Bad Gateway",
        r"Error during validation",
    ]

class ValidatorCheckerPm2LogOutputSn36(ValidatorCheckerPm2LogOutput):
    _generic_patterns = []

class ValidatorCheckerPm2LogOutputSn38(ValidatorCheckerPm2LogOutput):
    _subnet_patterns = [r"\[Errno -2\] Name or service not known"]

class ValidatorCheckerPm2LogOutputSn41(ValidatorCheckerPm2LogOutput):
    _generic_patterns = []

class ValidatorCheckerPm2LogOutputSn42(ValidatorCheckerPm2LogOutput):
    _subnet_patterns = [r"EOF occurred in violation of protocol"]

class ValidatorCheckerPm2LogOutputSn43(ValidatorCheckerPm2LogOutput):
    _subnet_patterns = [r"Error during validation"]

class ValidatorCheckerPm2LogOutputSn46(ValidatorCheckerPm2LogOutput):
    _generic_patterns = []

class ValidatorCheckerPm2LogOutputSn52(ValidatorCheckerPm2LogOutput):
    _generic_patterns = []
    _subnet_patterns = [r"websockets\.exceptions\.InvalidStatus"]

# class ValidatorCheckerPm2LogOutputSn55(ValidatorCheckerPm2LogOutput):
#     _subnet_patterns = [r"TimeoutError"]

class ValidatorCheckerPm2LogOutputSn79(ValidatorCheckerPm2LogOutput):
    _generic_patterns = []

class ValidatorCheckerPm2LogOutputSn83(ValidatorCheckerPm2LogOutput):
    _generic_patterns = []
