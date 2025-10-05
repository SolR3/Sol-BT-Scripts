# standard imports
import argparse


# Constants
DEFAULT_TIME_THRESHOLD = 23  # 1 day
DEFAULT_CHECK_INTERVAL = 1  # 1 hour


def parse_ensure_set_weights_args(args_str=None):
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-n", "--netuids",
        type=int,
        nargs="+",
        required=True,
        help="The uids of the subnets to check."
    )

    parser.add_argument(
        "--time-threshold",
        type=float,
        help="The threshold value in hours above which to manually set weights. "
             f"Default: {DEFAULT_TIME_THRESHOLD}"
    )

    parser.add_argument(
        "--check-interval",
        type=float,
        help="The interval in hours to check whether weights need to be "
             f"manually set. Default: {DEFAULT_CHECK_INTERVAL}"
    )

    parser.add_argument(
        "--skip-discord-notify",
        action="store_false",
        dest="discord_notify",
        help="When specified, this will skip sending the notification to the "
             "discord monitor channel."
    )

    # If args_str was not passed to this function then it's being called
    # from ensure_set_weights, so set the defaults. Otherwise it's being
    # called from update_ensure_set_weights, in which case we don't want
    # default values for any args that weren't passed into the function.
    if args_str is None:
        parser.set_defaults(
            time_threshold=DEFAULT_TIME_THRESHOLD,
            check_interval=DEFAULT_CHECK_INTERVAL
        )

    return parser.parse_args(args_str)
