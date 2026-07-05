# Standard imports
import argparse

# Local imports
from .constants import (
    DEFAULT_UPDATED_THRESHOLD,
    DEFAULT_VTRUST_THRESHOLD,
    DEFAULT_STOPPED_LOGS_THRESHOLD,
    DEFAULT_LOG_ERRORS_RESTART_WAIT_TIME,
    )


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-n",
        type=int,
        required=True,
        dest="netuid",
        help="The uid of the subnet.")

    parser.add_argument(
        "--restart-script",
        required=True,
        help="The restart script path.")

    parser.add_argument(
        "--restart-venv",
        help="The restart venv path.")

    parser.add_argument(
        "--pm2-process", # Keeping arg name singular to avoid confusion.
        nargs="+",
        default=[],
        dest="pm2_processes",
        help="Restart the validator based on pm2 log patterns or stopped pm2 "
             "log output. The value passed to this arg is the name of the pm2 "
             "process to monitor. Multiple pm2 processes may be passed to this "
             "arg.")

    parser.add_argument(
        "--docker-container", # Keeping arg name singular to avoid confusion.
        nargs="+",
        default=[],
        dest="docker_containers",
        help="Restart the validator based on docker log patterns. The value "
             "passed to this arg is the name of the docker container to monitor. "
             "Multiple docker containers may be passed to this arg.")

    parser.add_argument(
        "--local-subtensor",
        help="Deprecated. This arg no longer needs to be specified. "
             "The restarter automatically rotates between all local "
             "subtensors.")

    parser.add_argument(
        "--updated-threshold",
        type=int,
        default=DEFAULT_UPDATED_THRESHOLD,
        help="The Updated threshold value above which to restart the "
             "validator. This value is in blocks. "
             f"Default: {DEFAULT_UPDATED_THRESHOLD}")

    parser.add_argument(
        "--updated-mechid",
        type=int,
        default=0,
        help="The mechanism on which to check the updated value (i.e. 0, 1). "
             "When not specified the default mech 0 is checked.")

    parser.add_argument(
        "--vtrust-threshold",
        type=float,
        default=DEFAULT_VTRUST_THRESHOLD,
        help="The vTrust threshold value below which to restart the "
             "validator. "
             f"Default: {DEFAULT_VTRUST_THRESHOLD}")

    parser.add_argument(
        "--stopped-logs-threshold",
        type=float,
        default=DEFAULT_STOPPED_LOGS_THRESHOLD,
        help="The time in minutes after which to restart the process if the "
             "pm2 log files haven't updated. "
             f"Default: {DEFAULT_STOPPED_LOGS_THRESHOLD}")

    parser.add_argument(
        "--log-errors-restart-wait-time",
        type=float,
        default=DEFAULT_LOG_ERRORS_RESTART_WAIT_TIME,
        help="The number of minutes to wait after restarting a the validator "
             "due to a pm2 log patterns error so it doesn't get restarted multiple "
             "times due to duplicate or quickly recurring error patterns. NOTE: "
             "this only applies to pm2 logs. Docker logs are unaffected by this."
             f"Default: {DEFAULT_LOG_ERRORS_RESTART_WAIT_TIME}")

    parser.add_argument(
        "--code-repo-path",
        action="append",
        help="When specified, check this path for git code updates. When not specified, "
             "the current directory is checked. This arg can be specified multiple times "
             "to check multiple code repos.")

    parser.add_argument(
        "--code-check-tags",
        action="store_true",
        help="When specified, this will check for git repo updates by checking whether the "
             "latest tag is checked out. When not specified, this will check for the "
             "latest commit.")

    parser.add_argument(
        "--do-vtrust-check",
        action="store_true",
        dest="do_check_vtrust",
        help="When specified, this will do the checking of the vTrust value. "
             "Note: Unlike most of the other checks, this one is opt-in "
             "rather than opt-out.")
    
    parser.add_argument(
        "--skip-code-check",
        action="store_false",
        dest="do_check_code",
        help="When specified, this will do the checking for git code updates. "
             "Note: Unlike most of the other checks, this one is opt-in "
             "rather than opt-out. WARNING: This check currentl requires that the "
             "restarter be run from the base git repo folder.")

    parser.add_argument(
        "--skip-updated-check",
        action="store_false",
        dest="do_check_updated",
        help="When specified, this will skip the checking of the Updated value.")

    parser.add_argument(
        "--skip-blacklist-logs-check",
        action="store_false",
        dest="do_check_blacklist_logs",
        help="When specified, this will skip the checking of the log output "
             "for miner blackisting patterns.")

    parser.add_argument(
        "--skip-log-errors-check",
        action="store_false",
        dest="do_check_errors",
        help="When specified, this will skip the checking of the log output "
             "for error patterns.")

    parser.add_argument(
        "--skip-stopped-logs-check",
        action="store_false",
        dest="do_check_stopped_logs",
        help="When specified, this will skip the checking whether the pm2 log "
             "files sotpped udpdating.")

    parser.add_argument(
        "--skip-discord-notify",
        action="store_false",
        dest="discord_notify",
        help="When specified, this will skip sending the notification to the "
             "discord monitor channel.")

    parser.add_argument(
        "--skip-restarter-code-check",
        action="store_false",
        dest="do_check_restarter_code",
        help="When specified, this will do the checking for git code updates. "
             "Note: Unlike most of the other checks, this one is opt-in "
             "rather than opt-out. WARNING: This check currentl requires that the "
             "restarter be run from the base git repo folder.")

    return parser.parse_args()
