from __future__ import annotations

# Standard imports
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import os
import shlex
import subprocess
import time
from typing import Type, TYPE_CHECKING

# Bittensor import
import bittensor

# Local imports
from .checker_git_repo import (
    ValidatorCheckerGitUpdateCommits,
    ValidatorCheckerGitUpdateTags,
)
from .checker_log_output import ValidatorCheckerLogOutputFactory
from .checker_stopped_logs import (
    ValidatorCheckerDockerStoppedLogs,
    ValidatorCheckerPm2StoppedLogs,
)
from .checker_subtensor import (
    ValidatorCheckerUpdated,
    ValidatorCheckerVTrust,
)
from .constants import (
    AT_SOL,
    AT_USERS,
    DEBUG,
    RED_X,
    RESTARTER_GIT_PATHS,
    RESTARTER_PREFIX,
)
from .utils import (
    restart_lock,
    send_monitor_notification,
)

if TYPE_CHECKING:
    from .checker_base import ValidatorChecker


def log_info(message):
    bittensor.logging.info(f"{RESTARTER_PREFIX}: {message}")


def log_warning(message):
    bittensor.logging.warning(f"{RESTARTER_PREFIX}: {message}")


def log_error(message):
    bittensor.logging.error(f"{RESTARTER_PREFIX}: {message}")


@dataclass
class RestartChecker:
    descriptor: str
    checker_class: Type[ValidatorChecker]
    set_options: tuple[tuple[str, object]] = field(default_factory=tuple)


def _run_checker(checker_class, options):
    try:
        checker_class(options)
    except Exception as exc:
        import traceback

        traceback.print_exc()
        checker_class.log_error(f"Error: {exc}")
        send_monitor_notification(
            checker_class.log_prefix,
            f"{AT_USERS} {RED_X} restarter check \"{checker_class.log_prefix}\" "
            f"failed on subnet {options.netuid}"
        )


def notify_ip_address(options):
    # Debug helper function to send a discord notification with the host IP address
    # for netuids that may be running rogue restarter processes.

    # Populate this with the list of netuids who's restarter processes we want to find.
    netuids = []

    if options.netuid in netuids:
        import socket

        ip_address = None
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            ip_address = sock.getsockname()[0]
        except Exception as exc:
            import traceback

            traceback.print_exc()
            log_error(f"Error obtaining host IP address: {exc}")
        finally:
            sock.close()

        if ip_address:
            msg = f"IP address for host running restarter on subnet {options.netuid}: {ip_address}"
        else:
            msg = f"Failed to get IP address for host running restarter on subnet {options.netuid}"

        send_monitor_notification(RESTARTER_PREFIX, msg)


def check_for_restarter_code_update(netuid):

    def send_error(message):
        log_error(message)
        log_error("Not checking for restarter code updates.")
        send_monitor_notification(
            RESTARTER_PREFIX,
            f"{AT_SOL} {RED_X} Failed to update restarter git repo on subnet {netuid}"
        )

    # TODO: This duplicate code needs to be in a separate function.
    restarter_dir = os.path.dirname(__file__)
    repo_cmd = f"git -C {restarter_dir} rev-parse --show-toplevel"
    try:
        process = subprocess.run(shlex.split(repo_cmd), check=True, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        # Should never ever get here
        send_error(f"Could not find restarter git repo from path '{restarter_dir}': {exc}")
        return

    repo_path = process.stdout.decode().strip()

    def do_update():
        log_info("Checking for restarter code updates.")

        # Hard-coding these because it's just easier
        restarter_git_paths = shlex.join(RESTARTER_GIT_PATHS)

        # Get current commit
        get_cmd = f"git -C {repo_path} rev-parse HEAD"
        try:
            process = subprocess.run(shlex.split(get_cmd), check=True, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            send_error(f"'{get_cmd}' command failed: {exc}")
            return

        current_commit = process.stdout.decode().strip()

        # Run git pull
        pull_cmd = f"git -C {repo_path} pull --autostash"
        try:
            subprocess.run(shlex.split(pull_cmd), check=True)
        except subprocess.CalledProcessError as exc:
            send_error(f"'{pull_cmd}' command failed: {exc}")
            return

        # Get new commit
        try:
            process = subprocess.run(shlex.split(get_cmd), check=True, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            send_error(f"'{get_cmd}' command failed: {exc}")
            return

        new_commit = process.stdout.decode().strip()

        log_info(f"Current commit: {current_commit}")
        log_info(f"New commit: {new_commit}")
        if current_commit != new_commit:
            log_info("Commits changed.")
            diff_cmd = f"git -C {repo_path} diff --quiet {current_commit} {new_commit} -- {restarter_git_paths}"
            if subprocess.run(shlex.split(diff_cmd)).returncode:
                log_info("Restarter code changed. Exiting process. If this is running in pm2 "
                         "it should cause a pm2 restart and run the updated code.")
                with restart_lock:
                    # Sleeping for a second to make sure all logs are output before restarting.
                    # Flushing stdout/stderr doesn't seem to help.
                    time.sleep(1)
                    # Commenting this for now since this could cause 100+ discord notifications.
                    # send_monitor_notification(
                    #     RESTARTER_PREFIX,
                    #     f"Updating restarter git repo on subnet {netuid}"
                    # )
                    os._exit(1)
            else:
                log_info("Restarter code unchanged. Doing nothing.")
        else:
            log_info("Commits are the same. Doing nothing.")

    while True:
        do_update()

        sleep_interval = 3600  # 1 hour
        log_info(f"Sleeping for {sleep_interval} seconds.")
        time.sleep(sleep_interval)


def run(options):
    # options.do_check_blacklist_logs = False  # Temporarily force-disabling blacklist logs check

    if DEBUG:
        bittensor.logging.enable_debug()
    else:
        bittensor.logging.enable_info()

    notify_ip_address(options)

    if not (options.pm2_processes or options.docker_containers):
        if options.do_check_errors:
            log_warning(
                "No --pm2-process or --docker-container is specified. "
                "Not checking for log errors.")
            options.do_check_errors = False

        if options.do_check_stopped_logs:
            log_warning(
                "No --pm2-process or --docker-container is specified. "
                "Not checking for stopped log output.")
            options.do_check_stopped_logs = False

        if options.do_check_blacklist_logs:
            log_warning(
                "No --pm2-process or --docker-container is specified. "
                "Not checking for miner blackisting in logs.")
            options.do_check_blacklist_logs = False

    sleep_time = 15
    log_info("")
    log_info(f"Starting validator restarter on subnet {options.netuid}")
    log_info(f"Sleeping {sleep_time} seconds in case the "
             "validator process is just starting.")
    log_info("")
    time.sleep(sleep_time)

    # Gather all restart checks
    restart_checks = []

    # Add updated check
    if options.do_check_updated:
        restart_checks.append(
            RestartChecker(
                descriptor="Updated value",
                checker_class=ValidatorCheckerUpdated
            )
        )

    # Add vtrust check
    if options.do_check_vtrust:
        restart_checks.append(
            RestartChecker(
                descriptor="vTrust value",
                checker_class=ValidatorCheckerVTrust
            )
        )

    # Add log errors checks
    if options.do_check_errors or options.do_check_blacklist_logs:
        for docker_container in options.docker_containers:
            restart_checks.append(
                RestartChecker(
                    descriptor="docker log output",
                    checker_class=ValidatorCheckerLogOutputFactory,
                    set_options=(
                        ("log_checker_type", "Docker"), ("docker_container", docker_container),
                    )
                )
            )
        for pm2_process in options.pm2_processes:
            restart_checks.append(
                RestartChecker(
                    descriptor="pm2 log output",
                    checker_class=ValidatorCheckerLogOutputFactory,
                    set_options=(
                        ("log_checker_type", "Pm2"), ("pm2_process", pm2_process),
                    )
                )
            )

    # Add stopped logs checks
    if options.do_check_stopped_logs:
        for docker_container in options.docker_containers:
            restart_checks.append(
                RestartChecker(
                    descriptor="stopped docker logs",
                    checker_class=ValidatorCheckerDockerStoppedLogs,
                    set_options=(("docker_container", docker_container),)
                )
            )
        for pm2_process in options.pm2_processes:
            restart_checks.append(
                RestartChecker(
                    descriptor="stopped pm2 logs",
                    checker_class=ValidatorCheckerPm2StoppedLogs,
                    set_options=(("pm2_process", pm2_process),)
                )
            )

    # Add code update check
    if options.do_check_code:
        code_checker_class = (
            ValidatorCheckerGitUpdateTags if options.code_check_tags
            else ValidatorCheckerGitUpdateCommits
        )
        restart_checks.append(
            RestartChecker(
                descriptor="code update",
                checker_class=code_checker_class,
            )
        )

    # Run each check in a separate thread
    with ThreadPoolExecutor(max_workers=len(restart_checks)) as executor:
        while restart_checks:
            restart_check = restart_checks.pop(0)
            log_info("")
            log_info("="*(len(restart_check.descriptor)+18))
            log_info(f"Running {restart_check.descriptor} checker.")
            log_info("="*(len(restart_check.descriptor)+18))
            log_info("")

            for (attr, value) in restart_check.set_options:
                setattr(options, attr, value)
            executor.submit(_run_checker, restart_check.checker_class, options)

            if restart_checks:
                log_info(f"Sleeping {sleep_time} seconds before "
                         "starting the next one.")
                time.sleep(sleep_time)

        log_info("Started all restart checkers.")
        if options.do_check_restarter_code:
            log_info(f"Sleeping {sleep_time} seconds before checking for "
                     "restarter code updates.")
            time.sleep(sleep_time)
            check_for_restarter_code_update(options.netuid)
