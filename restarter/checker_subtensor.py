# Standard imports
import multiprocessing
import random
import time

# Bittensor import
import bittensor

# Local imports
from .checker_base import ValidatorChecker
from .constants import (
    RIZZO_COLDKEY,
    RIZZO_HOTKEYS,
    MULTI_UID_HOTKEYS,
)


# Multiprocessing Queues
UPDATED_MP_QUEUE = None
VTRUST_MP_QUEUE = None


class MetagraphData:
    # Replace the last_update value in the metagraph with
    # the last_update value in the metagraph_info because
    # only that one is accurate for mechid's other than 0.
    def __init__(self, metagraph, metagraph_info):
        self.netuid = metagraph.netuid
        self.hotkeys = metagraph.hotkeys
        self.coldkeys = metagraph.coldkeys
        self.block = metagraph.block
        self.last_update = metagraph_info.last_update
        self.Tv = metagraph.Tv


def get_metagraph_data(network, netuid, mechid, mp_queue_name):
    mp_queue = globals()[mp_queue_name]
    with bittensor.Subtensor(network=network) as subtensor:
        metagraph = subtensor.metagraph(netuid)
        metagraph_info = subtensor.get_metagraph_info(netuid, mechid=mechid)
        metagraph_data = MetagraphData(metagraph, metagraph_info)
        mp_queue.put(metagraph_data)


class ValidatorCheckerSubtensor(ValidatorChecker):
    # Updated and vTrust checkers only

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
        # Loop until we get a subtensor connection
        while True:
            self._local_subtensor_index = \
                (self._local_subtensor_index + 1) % len(self._local_subtensors)
            network_name = self._local_subtensors[self._local_subtensor_index]
            network = f"ws://subtensor-{network_name}.rizzo.network:9944"

            self.log_info(f"Connecting to subtensor network: {network}")
            try:
                args = [network, self._netuid, self._mechid, self._mp_queue_name]
                with multiprocessing.Pool(processes=1) as pool:
                    pool.apply(get_metagraph_data, args)
            except Exception as err:
                self.log_error("")
                self.log_error(f"Subtensor connection failed on '{network}'")
                self.log_error(f"{type(err).__name__}: {err}")
                self.log_error("")
                self.log_error("Rotating subtensors and trying again.")
                time.sleep(1)
            else:
                break

        mp_queue = globals()[self._mp_queue_name]
        return mp_queue.get()

    def _get_rizzo_uid(self, metagraph_data):
        if metagraph_data.netuid in MULTI_UID_HOTKEYS:
            try:
                return metagraph_data.hotkeys.index(
                    RIZZO_HOTKEYS[metagraph_data.netuid]
                )
            except ValueError:
                return None

        try:
            return metagraph_data.coldkeys.index(RIZZO_COLDKEY)
        except ValueError:
            return None


class ValidatorCheckerUpdated(ValidatorCheckerSubtensor):
    log_prefix = "CHECK UPDATED"

    def _init_setup(self, options):
        super()._init_setup()

        # Set restart threshold
        self._restart_threshold = options.updated_threshold

        # Set the mechanism to check
        self._mechid = options.updated_mechid

        # Create the multiprocessing queue for passing the metagraph data
        # from the subprocess back to the main process.
        global UPDATED_MP_QUEUE
        UPDATED_MP_QUEUE = multiprocessing.Queue()
        self._mp_queue_name = "UPDATED_MP_QUEUE"

    def _run(self):
        self.log_info("")
        self.log_info("Checking for high Updated values.")
        self.log_info("")

        default_sleep_time = 4320  # 360 blocks

        while True:
            metagraph_data = self._get_metagraph_data()
            rizzo_uid = self._get_rizzo_uid(metagraph_data)
            if rizzo_uid is None:
                self.log_warning(
                    f"Rizzo validator not running for subnet {self._netuid}. "
                )
                self.log_info(f"Sleeping for {default_sleep_time} seconds.")
                time.sleep(default_sleep_time)
                continue

            rizzo_updated = int(
                metagraph_data.block - metagraph_data.last_update[rizzo_uid])
            self.log_info("")
            self.log_info(f"Rizzo Updated on mechid {self._mechid} is {rizzo_updated} blocks.")

            if self._check_for_restart:
                # If the rizzo updated value is greater than the restart threshold
                # the do a restart and set _check_for_restart to False.
                self.log_info("Updated value check for restart is True.")
                if rizzo_updated >= self._restart_threshold:
                    self.log_info(f"Updated value {rizzo_updated} "
                                   f">= {self._restart_threshold}")
                    self._restart_validator(f"Updated value is {rizzo_updated}")
                    self.log_info("Setting check for restart to False.")
                    self._check_for_restart = False
                else:
                    self.log_info(f"Updated value {rizzo_updated} "
                                   f"< {self._restart_threshold}")
                    self.log_info("Doing nothing.")
            else:
                # If the rizzo updated value is less than the restart threshold
                # then set _check_for_restart to True.
                self.log_info("Updated value Check for restart is False.")
                if rizzo_updated < self._restart_threshold:
                    self.log_info(f"Updated value {rizzo_updated} "
                                   f"< {self._restart_threshold}")
                    self.log_info("Setting check for restart to True.")
                    self._check_for_restart = True
                else:
                    self.log_info(f"Updated value {rizzo_updated} "
                                   f">= {self._restart_threshold}")
                    self.log_info("Doing nothing.")

            seconds_until_threshold = \
                (self._restart_threshold - rizzo_updated) * 12
            sleep_interval = (seconds_until_threshold
                              if seconds_until_threshold > 0
                              else default_sleep_time)
            self.log_info(f"Sleeping for {sleep_interval} seconds.")
            time.sleep(sleep_interval)


class ValidatorCheckerVTrust(ValidatorCheckerSubtensor):
    log_prefix = "CHECK VTRUST"

    def _init_setup(self, options):
        super()._init_setup()

        # Set restart threshold
        self._restart_threshold = options.vtrust_threshold

        # Set the mechanism to check
        # This is always 0 because the vTrust is the same across all mechanisms.
        self._mechid = 0

        # Create the multiprocessing queue for passing the metagraph data
        # from the subprocess back to the main process.
        global VTRUST_MP_QUEUE
        VTRUST_MP_QUEUE = multiprocessing.Queue()
        self._mp_queue_name = "VTRUST_MP_QUEUE"

    def _run(self):
        self.log_info("")
        self.log_info("Checking for low vTrust values.")
        self.log_info("")

        sleep_interval = 4320  # 360 blocks

        while True:
            metagraph_data = self._get_metagraph_data()
            rizzo_uid = self._get_rizzo_uid(metagraph_data)
            if rizzo_uid is None:
                self.log_warning(
                    f"Rizzo validator not running for subnet {self._netuid}. "
                )
                self.log_info(f"Sleeping for {sleep_interval} seconds.")
                time.sleep(sleep_interval)
                continue

            rizzo_vtrust = metagraph_data.Tv[rizzo_uid]
            vtrust_str = f"{rizzo_vtrust:.5f}"

            self.log_info("")
            self.log_info(f"Rizzo vTrust is {vtrust_str}")

            if self._check_for_restart:
                # If the rizzo vTrust value is less than the restart threshold
                # the do a restart and set _check_for_restart to False.
                self.log_info("vTrust value check for restart is True.")
                if rizzo_vtrust < self._restart_threshold:
                    self.log_info(f"vTrust value {vtrust_str} "
                                   f"< {self._restart_threshold}")
                    self._restart_validator(f"vTrust value is {vtrust_str}")
                    self.log_info("Setting check for restart to False.")
                    self._check_for_restart = False
                else:
                    self.log_info(f"vTrust value {vtrust_str} "
                                   f">= {self._restart_threshold}")
                    self.log_info("Doing nothing.")
            else:
                # If the rizzo vTrust value is greater than the restart threshold
                # then set _check_for_restart to True.
                self.log_info("vTrust value Check for restart is False.")
                if rizzo_vtrust >= self._restart_threshold:
                    self.log_info(f"vTrust value {vtrust_str} "
                                   f">= {self._restart_threshold}")
                    self.log_info("Setting check for restart to True.")
                    self._check_for_restart = True
                else:
                    self.log_info(f"vTrust value {vtrust_str} "
                                   f"< {self._restart_threshold}")
                    self.log_info("Doing nothing.")

            self.log_info(f"Sleeping for {sleep_interval} seconds.")
            time.sleep(sleep_interval)
