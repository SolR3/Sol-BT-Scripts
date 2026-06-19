# Standard imports
import json
import os
import subprocess
import time

# Local imports
from .checker_base import ValidatorChecker


class ValidatorCheckerDockerStoppedLogs(ValidatorChecker):
    log_prefix = "CHECK DOCKER LOGS STOPPED"

    def _init_setup(self, options):
        self._docker_container = options.docker_container
        self._restart_threshold = int(round(options.stopped_logs_threshold * 60))

    def _run(self):
        from datetime import datetime
        try:
            import docker
        except ImportError:
            self.log_error("Could not import the docker python module. Not checking for stopped logs.")
            return

        self.log_info("")
        self.log_info(f"Checking for stopped logs for container: {self._docker_container}.")
        self.log_info("")

        client = docker.from_env()
        try:
            while True:
                # Get the docker container each time in case it was restarted
                # since the previous time.
                try:
                    container = client.containers.get(self._docker_container)
                except docker.errors.NotFound:
                    sleep_time = 60
                    self.log_warning(f"Could not find '{self._docker_container}' docker container.")
                    self.log_info(f"Sleeping {sleep_time} seconds.")
                    time.sleep(sleep_time)
                    continue

                try:
                    log_line = container.logs(timestamps=True, tail=1).decode()
                except docker.errors.APIError:
                    sleep_time = 60
                    self.log_warning(f"Could not obtain logs from '{self._docker_container}' docker container.")
                    self.log_info(f"Sleeping {sleep_time} seconds.")
                    time.sleep(sleep_time)
                    continue

                timestamp = log_line.split()[0].split(".")[0]
                log_time = datetime.fromisoformat(timestamp)
                log_ctime = log_time.strftime("%a %b %d %H:%M:%S %Y")

                current_time = datetime.now()
                current_ctime = current_time.strftime("%a %b %d %H:%M:%S %Y")

                self.log_info("")
                self.log_info(f"Docker container: {self._docker_container}")
                self.log_info(f"Last log output: {log_ctime}")
                self.log_info(f"Current time: {current_ctime}")

                time_diff = int((current_time - log_time).total_seconds())
                if time_diff >= self._restart_threshold:
                    self.log_info(f"Time difference {time_diff} seconds "
                                f">= {self._restart_threshold} seconds")
                    log_minutes = time_diff / 60
                    self._restart_validator(f"No log output in {log_minutes:.1f} minutes.")
                else:
                    self.log_info(f"Time difference {time_diff} seconds "
                                f"< {self._restart_threshold} seconds")
                    self.log_info("Doing nothing.")

                seconds_until_threshold = \
                    (self._restart_threshold - time_diff)
                sleep_interval = (seconds_until_threshold
                                if seconds_until_threshold > 0
                                else self._restart_threshold)
                self.log_info(f"Sleeping for {sleep_interval} seconds.")
                time.sleep(sleep_interval)
        finally:
            client.close()


class ValidatorCheckerPm2StoppedLogs(ValidatorChecker):
    log_prefix = "CHECK PM2 LOGS STOPPED"

    def _init_setup(self, options):
        self._pm2_process = options.pm2_process
        self._restart_threshold = int(round(options.stopped_logs_threshold * 60))

    def _run(self):
        self.log_info("")
        self.log_info(f"Checking for stopped logs for process: {self._pm2_process}.")
        self.log_info("")

        while True:
            out_log_file = None
            error_log_file = None

            process = subprocess.run(["pm2", "jlist"], stdout=subprocess.PIPE)
            pm2_output = json.loads(process.stdout)
            for pm2_process in pm2_output:
                if pm2_process["name"] == self._pm2_process:
                    out_log_file = pm2_process["pm2_env"]["pm_out_log_path"]
                    error_log_file = pm2_process["pm2_env"]["pm_err_log_path"]
                    break

            if not out_log_file:
                raise Exception(f"Could not find out log file for pm2 process {self._pm2_process}")
            if not error_log_file:
                raise Exception(f"Could not find error log file for pm2 process {self._pm2_process}")

            if not os.path.isfile(out_log_file):
                raise Exception(f"Out log file does not exist: {out_log_file}")
            if not os.path.isfile(error_log_file):
                raise Exception(f"Error log file does not exist: {error_log_file}")

            self.log_info("")
            self.log_info(f"Out log file: {out_log_file}")
            self.log_info(f"Error log file: {error_log_file}")

            out_log_file_mtime = int(os.path.getmtime(out_log_file))
            error_log_file_mtime = int(os.path.getmtime(error_log_file))
            current_time = int(time.time())
            out_log_file_ctime = time.ctime(out_log_file_mtime)
            error_log_file_ctime = time.ctime(error_log_file_mtime)
            current_ctime = time.ctime(current_time)
            self.log_info("")
            self.log_info(f"Out Log file last modified: {out_log_file_ctime}")
            self.log_info(f"Error Log file last modified: {error_log_file_ctime}")
            self.log_info(f"Current time: {current_ctime}")

            time_diff = current_time - max(out_log_file_mtime, error_log_file_mtime)
            if time_diff >= self._restart_threshold:
                self.log_info(f"Time difference {time_diff} seconds "
                               f">= {self._restart_threshold} seconds")
                log_minutes = time_diff / 60
                self._restart_validator(f"No log output in {log_minutes:.1f} minutes.")
            else:
                self.log_info(f"Time difference {time_diff} seconds "
                               f"< {self._restart_threshold} seconds")
                self.log_info("Doing nothing.")

            seconds_until_threshold = \
                (self._restart_threshold - time_diff)
            sleep_interval = (seconds_until_threshold
                              if seconds_until_threshold > 0
                              else self._restart_threshold)
            self.log_info(f"Sleeping for {sleep_interval} seconds.")
            time.sleep(sleep_interval)
