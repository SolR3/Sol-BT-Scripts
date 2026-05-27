# Standard imports
import multiprocessing
import os
import pickle
import random
import time

# Local imports
from .checker_base import ValidatorChecker


class MetagraphData:
    def __init__(self, metagraph):
        self.netuid = metagraph.netuid
        self.hotkeys = metagraph.hotkeys
        self.coldkeys = metagraph.coldkeys
        self.block = metagraph.block
        self.last_update = metagraph.last_update
        self.Tv = metagraph.Tv


def get_metagraph_data(network, netuid, pickle_file, log_prefix):
    import bittensor

    with bittensor.Subtensor(network=network) as subtensor:
        metagraph = subtensor.metagraph(netuid=netuid)
        metagraph_data = MetagraphData(metagraph)
        bittensor.logging.info(f"{log_prefix}: Writing pickle file: {pickle_file}")
        with open(pickle_file, "wb") as fp:
            pickle.dump(metagraph_data, fp)


class ValidatorCheckerSubtensor(ValidatorChecker):
    # Updated and vTrust checkers only

    _rizzo_coldkey = "5FuzgvtfbZWdKSRxyYVPAPYNaNnf9cMnpT7phL3s2T3Kkrzo"

    # This is a fix to handle the subnets on which we're registered on
    # multiple uids.
    _multi_uid_hotkeys = {
        20: "5ExaAP3ENz3bCJufTzWzs6J6dCWuhjjURT8AdZkQ5qA4As2o",
    }

    _local_subtensors = [
        "cali",
        "candyland",
        "datacenter01",
        "la",
        "moonbase",
        "titan",
    ]

    def _init_setup(self):
        # Start false in case this is added after a manual restart.
        self._check_for_restart = False

        # Randomize local subtensor.
        random.seed()
        self._local_subtensor_index = random.randint(0, len(self._local_subtensors) - 1)

    def _get_metagraph_data(self):
        pickle_file = os.path.join(
            os.path.expanduser("~"), self._pickle_file_name
        )
        # Loop until we get a subtensor connection
        while True:
            self._local_subtensor_index = \
                (self._local_subtensor_index + 1) % len(self._local_subtensors)
            network_name = self._local_subtensors[self._local_subtensor_index]
            network = f"ws://subtensor-{network_name}.rizzo.network:9944"

            self._log_info(f"Connecting to subtensor network: {network}")
            try:
                args = [network, self._netuid, pickle_file, self.log_prefix]
                with multiprocessing.Pool(processes=1) as pool:
                    pool.apply(get_metagraph_data, args)
            except Exception as err:
                self._log_error("")
                self._log_error(f"Subtensor connection failed on '{network}'")
                self._log_error(f"{type(err).__name__}: {err}")
                self._log_error("")
                self._log_error("Rotating subtensors and trying again.")
                time.sleep(1)
            else:
                break

        # read pickle file
        if not os.path.isfile(pickle_file):
            self._log_error(
                f"Pickle file {pickle_file} does not exist, "
                "could not get metagraph data."
            )
            return None

        self._log_info(f"Reading pickle file: {pickle_file}")
        with open(pickle_file, "rb") as fp:
            metagraph_data = pickle.load(fp)
        os.unlink(pickle_file)
        return metagraph_data

    def _get_rizzo_uid(self, metagraph_data):
        if metagraph_data.netuid in self._multi_uid_hotkeys:
            try:
                return metagraph_data.hotkeys.index(
                    self._multi_uid_hotkeys[metagraph_data.netuid]
                )
            except ValueError:
                return None

        try:
            return metagraph_data.coldkeys.index(self._rizzo_coldkey)
        except ValueError:
            return None


class ValidatorCheckerUpdated(ValidatorCheckerSubtensor):
    log_prefix = "CHECK UPDATED"

    def _init_setup(self, options):
        super()._init_setup()

        # Set restart threshold
        self._restart_threshold = options.updated_threshold

        self._pickle_file_name = "metagraph_updated.pickle"

    def _run(self):
        self._log_info("")
        self._log_info("Checking for high Updated values.")
        self._log_info("")

        default_sleep_time = 4320  # 360 blocks

        while True:
            metagraph_data = self._get_metagraph_data()
            if not metagraph_data:
                self._log_error(
                    "Could not get metagraph. Not checking Updated value. "
                )
                self._log_info(f"Sleeping for {default_sleep_time} seconds.")
                time.sleep(default_sleep_time)
                continue

            rizzo_uid = self._get_rizzo_uid(metagraph_data)
            if rizzo_uid is None:
                self._log_warning(
                    f"Rizzo validator not running for subnet {self._netuid}. "
                )
                self._log_info(f"Sleeping for {default_sleep_time} seconds.")
                time.sleep(default_sleep_time)
                continue

            rizzo_updated = int(
                metagraph_data.block - metagraph_data.last_update[rizzo_uid])
            self._log_info("")
            self._log_info(f"Rizzo Updated is {rizzo_updated} blocks.")

            if self._check_for_restart:
                # If the rizzo updated value is greater than the restart threshold
                # the do a restart and set _check_for_restart to False.
                self._log_info("Updated value check for restart is True.")
                if rizzo_updated >= self._restart_threshold:
                    self._log_info(f"Updated value {rizzo_updated} "
                                   f">= {self._restart_threshold}")
                    self._restart_validator(f"Updated value is {rizzo_updated}")
                    self._log_info("Setting check for restart to False.")
                    self._check_for_restart = False
                else:
                    self._log_info(f"Updated value {rizzo_updated} "
                                   f"< {self._restart_threshold}")
                    self._log_info("Doing nothing.")
            else:
                # If the rizzo updated value is less than the restart threshold
                # then set _check_for_restart to True.
                self._log_info("Updated value Check for restart is False.")
                if rizzo_updated < self._restart_threshold:
                    self._log_info(f"Updated value {rizzo_updated} "
                                   f"< {self._restart_threshold}")
                    self._log_info("Setting check for restart to True.")
                    self._check_for_restart = True
                else:
                    self._log_info(f"Updated value {rizzo_updated} "
                                   f">= {self._restart_threshold}")
                    self._log_info("Doing nothing.")

            seconds_until_threshold = \
                (self._restart_threshold - rizzo_updated) * 12
            sleep_interval = (seconds_until_threshold
                              if seconds_until_threshold > 0
                              else default_sleep_time)
            self._log_info(f"Sleeping for {sleep_interval} seconds.")
            time.sleep(sleep_interval)


class ValidatorCheckerVTrust(ValidatorCheckerSubtensor):
    log_prefix = "CHECK VTRUST"

    def _init_setup(self, options):
        super()._init_setup()

        # Set restart threshold
        self._restart_threshold = options.vtrust_threshold

        self._pickle_file_name = "metagraph_vtrust.pickle"

    def _run(self):
        self._log_info("")
        self._log_info("Checking for low vTrust values.")
        self._log_info("")

        sleep_interval = 4320  # 360 blocks

        while True:
            metagraph_data = self._get_metagraph_data()
            if not metagraph_data:
                self._log_error(
                    "Could not get metagraph. Not checking vTrust value. "
                )
                self._log_info(f"Sleeping for {sleep_interval} seconds.")
                time.sleep(sleep_interval)
                continue

            rizzo_uid = self._get_rizzo_uid(metagraph_data)
            if rizzo_uid is None:
                self._log_warning(
                    f"Rizzo validator not running for subnet {self._netuid}. "
                )
                self._log_info(f"Sleeping for {sleep_interval} seconds.")
                time.sleep(sleep_interval)
                continue

            rizzo_vtrust = metagraph_data.Tv[rizzo_uid]
            vtrust_str = f"{rizzo_vtrust:.5f}"

            self._log_info("")
            self._log_info(f"Rizzo vTrust is {vtrust_str}")

            if self._check_for_restart:
                # If the rizzo vTrust value is less than the restart threshold
                # the do a restart and set _check_for_restart to False.
                self._log_info("vTrust value check for restart is True.")
                if rizzo_vtrust < self._restart_threshold:
                    self._log_info(f"vTrust value {vtrust_str} "
                                   f"< {self._restart_threshold}")
                    self._restart_validator(f"vTrust value is {vtrust_str}")
                    self._log_info("Setting check for restart to False.")
                    self._check_for_restart = False
                else:
                    self._log_info(f"vTrust value {vtrust_str} "
                                   f">= {self._restart_threshold}")
                    self._log_info("Doing nothing.")
            else:
                # If the rizzo vTrust value is greater than the restart threshold
                # then set _check_for_restart to True.
                self._log_info("vTrust value Check for restart is False.")
                if rizzo_vtrust >= self._restart_threshold:
                    self._log_info(f"vTrust value {vtrust_str} "
                                   f">= {self._restart_threshold}")
                    self._log_info("Setting check for restart to True.")
                    self._check_for_restart = True
                else:
                    self._log_info(f"vTrust value {vtrust_str} "
                                   f"< {self._restart_threshold}")
                    self._log_info("Doing nothing.")

            self._log_info(f"Sleeping for {sleep_interval} seconds.")
            time.sleep(sleep_interval)
