from __future__ import annotations

# Standard imports
from dataclasses import dataclass
import multiprocessing
import os
import pickle
import random
import tempfile
import time
from typing import TYPE_CHECKING

# Local imports
from .checker_base import ValidatorChecker
from .constants import (
    RIZZO_COLDKEY,
    RIZZO_HOTKEYS,
    MULTI_UID_HOTKEYS,
    RED_X,
)
from .utils import (
    logger,
    send_monitor_notification
)

if TYPE_CHECKING:
    import numpy

# Multiprocessing Queues
UPDATED_MP_QUEUE = None
VTRUST_MP_QUEUE = None


@dataclass
class SubtensorData:
    netuid: int
    hotkeys: list[str]
    coldkeys: list[str]
    block: int
    last_update: numpy.ndarray | list[int]
    validator_trust: numpy.ndarray | list[float]


def get_subtensor_data_from_bt_11(log_prefix, network, netuid, mechid):
    import bittensor

    def _index(netuid, mechid):
        return mechid * bittensor.settings.GLOBAL_MAX_SUBNET_COUNT + netuid

    logger.info(f"{log_prefix}: Connecting to subtensor network: {network}")
    with bittensor.Subtensor(network=network) as subtensor:
        metagraph = subtensor.subnets.metagraph(netuid=netuid)
        validator_trust = subtensor.query(
            bittensor.storage.SubtensorModule.ValidatorTrust,
            params=[netuid]
        )
        last_update = subtensor.query(
            bittensor.storage.SubtensorModule.LastUpdate,
            params=[_index(netuid, mechid)]
        )

    validator_trust = [(vt / bittensor.settings.U16_MAX) for vt in validator_trust]

    subtensor_data = SubtensorData(
        netuid=metagraph.netuid,
        hotkeys=metagraph.hotkeys,
        coldkeys=metagraph.coldkeys,
        block=metagraph.block,
        last_update=last_update,
        validator_trust=validator_trust,
    )

    return subtensor_data


def get_subtensor_data_from_bt_10(log_prefix, network, netuid, mechid):
    import bittensor

    logger.info(f"{log_prefix}: Connecting to subtensor network: {network}")
    with bittensor.Subtensor(network=network) as subtensor:
        metagraph = subtensor.metagraph(netuid)
        metagraph_info = subtensor.get_metagraph_info(netuid, mechid=mechid)

    subtensor_data = SubtensorData(
        netuid=metagraph.netuid,
        hotkeys=metagraph.hotkeys,
        coldkeys=metagraph.coldkeys,
        block=int(metagraph.block),
        last_update=metagraph_info.last_update,
        validator_trust=metagraph.Tv,
    )

    return subtensor_data


def get_subtensor_data(log_prefix, network, netuid, mechid):
    import bittensor

    if int(bittensor.__version__.split(".")[0]) >= 11:
        return get_subtensor_data_from_bt_11(log_prefix, network, netuid, mechid)
    else:
        return get_subtensor_data_from_bt_10(log_prefix, network, netuid, mechid)


def write_subtensor_data_to_mp_queue(log_prefix, network, netuid, mechid, mp_queue_name):
    subtensor_data = get_subtensor_data(log_prefix, network, netuid, mechid)
    globals()[mp_queue_name].put(subtensor_data)


def write_subtensor_data_to_pkl_file(log_prefix, network, netuid, mechid, pickle_file):
    subtensor_data = get_subtensor_data(log_prefix, network, netuid, mechid)
    logger.info(f"{log_prefix}: Writing pickle file: {pickle_file}")
    with open(pickle_file, "wb") as fp:
        pickle.dump(subtensor_data, fp)


class ValidatorCheckerSubtensor(ValidatorChecker):
    log_prefix = "CHECK SUBTENSOR"

    _local_subtensors = [
        "cali",
        "candyland",
        "datacenter01",
        "la",
        "moonbase",
        "titan",
    ]

    def __new__(cls, options):
        if cls is not ValidatorCheckerSubtensor:
            return super().__new__(cls)

        checker_type = options.checker_type
        get_method = "PklFile" if options.use_pickle_file else "MpQueue"

        class_name = f"ValidatorChecker{checker_type}{get_method}"
        class_obj = globals()[class_name]
        class_obj.log_info(f"Running checker class: {class_name}")

        return super().__new__(class_obj)

    def _init_setup(self, *args, **kwargs):
        # Start false in case this is added after a manual restart.
        self._check_for_restart = False

        # Randomize local subtensor.
        random.seed()
        self._local_subtensor_index = random.randint(0, len(self._local_subtensors) - 1)

    def _get_subtensor_data(self, *subprocess_args):
        # Loop until we get a subtensor connection
        while True:
            self._local_subtensor_index = \
                (self._local_subtensor_index + 1) % len(self._local_subtensors)
            network_name = self._local_subtensors[self._local_subtensor_index]
            network = f"ws://subtensor-{network_name}.rizzo.network:9944"

            get_subtensor_data_func = globals()[self._get_subtensor_data_func]
            args = [self.log_prefix, network, self._netuid, self._mechid, *subprocess_args]
            try:
                with multiprocessing.Pool(processes=1) as pool:
                    pool.apply(get_subtensor_data_func, args)
            except (TypeError, ValueError):
                raise
            except Exception as err:
                self.log_error("")
                self.log_error(f"Subtensor connection failed on '{network}'")
                self.log_error(f"{type(err).__name__}: {err}")
                self.log_error("")
                self.log_error("Rotating subtensors and trying again.")
                time.sleep(1)
            else:
                break

    def _get_rizzo_uid(self, subtensor_data):
        if subtensor_data.netuid in MULTI_UID_HOTKEYS:
            try:
                return subtensor_data.hotkeys.index(
                    RIZZO_HOTKEYS[subtensor_data.netuid]
                )
            except ValueError:
                return None

        try:
            return subtensor_data.coldkeys.index(RIZZO_COLDKEY)
        except ValueError:
            return None


class ValidatorCheckerMpQueue(ValidatorCheckerSubtensor):
    _get_subtensor_data_func = "write_subtensor_data_to_mp_queue"

    def _init_setup(self, *args, **kwargs):
        super()._init_setup(*args, **kwargs)

        # Create the multiprocessing queue for passing the subtensor data
        # from the subprocess back to the main process.
        globals()[self._mp_queue_name] = multiprocessing.Queue()

    def _get_subtensor_data(self):
        super()._get_subtensor_data(self._mp_queue_name)

        return globals()[self._mp_queue_name].get()


class ValidatorCheckerPklFile(ValidatorCheckerSubtensor):
    _get_subtensor_data_func = "write_subtensor_data_to_pkl_file"

    def _get_subtensor_data(self):
        fp, pickle_file = tempfile.mkstemp(prefix=self._pickle_file_name + "_", suffix=".pkl")
        os.close(fp)

        try:
            super()._get_subtensor_data(pickle_file)

            # read pickle file
            if not os.path.isfile(pickle_file):
                self.log_error(f"Pickle file {pickle_file} does not exist, could not get subtensor data.")
                return None

            self.log_info(f"Reading pickle file: {pickle_file}")
            with open(pickle_file, "rb") as fp:
                return pickle.load(fp)

        finally:
            if os.path.isfile(pickle_file):
                os.unlink(pickle_file)


class ValidatorCheckerUpdated(ValidatorCheckerSubtensor):
    log_prefix = "CHECK UPDATED"

    def _init_setup(self, options):
        super()._init_setup(options)

        # Set restart threshold
        self._restart_threshold = options.updated_threshold

        # Set the mechanism to check
        self._mechid = options.updated_mechid

    def _run(self):
        self.log_info("")
        self.log_info("Checking for high Updated values.")
        self.log_info("")

        default_sleep_time = 4320  # 360 blocks

        while True:
            subtensor_data = self._get_subtensor_data()
            if not subtensor_data:
                self.log_error(
                    "Could not get subtensor. Not checking Updated value. "
                )
                send_monitor_notification(
                    self.log_prefix,
                    f"{RED_X} Failed to check updated value on subnet {self._netuid}"
                )
                self.log_info(f"Sleeping for {default_sleep_time} seconds.")
                time.sleep(default_sleep_time)
                continue

            rizzo_uid = self._get_rizzo_uid(subtensor_data)
            if rizzo_uid is None:
                self.log_warning(
                    f"Rizzo validator not running for subnet {self._netuid}. "
                )
                self.log_info(f"Sleeping for {default_sleep_time} seconds.")
                time.sleep(default_sleep_time)
                continue

            rizzo_updated = int(
                subtensor_data.block - subtensor_data.last_update[rizzo_uid])
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
        super()._init_setup(options)

        # Set restart threshold
        self._restart_threshold = options.vtrust_threshold

        # Set the mechanism to check
        # This is always 0 because the vTrust is the same across all mechanisms.
        self._mechid = 0

    def _run(self):
        self.log_info("")
        self.log_info("Checking for low vTrust values.")
        self.log_info("")

        sleep_interval = 4320  # 360 blocks

        while True:
            subtensor_data = self._get_subtensor_data()
            if not subtensor_data:
                self.log_error(
                    "Could not get subtensor. Not checking vTrust value. "
                )
                send_monitor_notification(
                    self.log_prefix,
                    f"{RED_X} Failed to check vTrust value on subnet {self._netuid}"
                )
                self.log_info(f"Sleeping for {sleep_interval} seconds.")
                time.sleep(sleep_interval)
                continue

            rizzo_uid = self._get_rizzo_uid(subtensor_data)
            if rizzo_uid is None:
                self.log_warning(
                    f"Rizzo validator not running for subnet {self._netuid}. "
                )
                self.log_info(f"Sleeping for {sleep_interval} seconds.")
                time.sleep(sleep_interval)
                continue

            rizzo_vtrust = subtensor_data.validator_trust[rizzo_uid]
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


class ValidatorCheckerUpdatedMpQueue(ValidatorCheckerMpQueue, ValidatorCheckerUpdated):
    _mp_queue_name = "UPDATED_MP_QUEUE"


class ValidatorCheckerUpdatedPklFile(ValidatorCheckerPklFile, ValidatorCheckerUpdated):
    _pickle_file_name = "subtensor_updated"


class ValidatorCheckerVTrustMpQueue(ValidatorCheckerMpQueue, ValidatorCheckerVTrust):
    _mp_queue_name = "VTRUST_MP_QUEUE"


class ValidatorCheckerVTrustPklFile(ValidatorCheckerPklFile, ValidatorCheckerVTrust):
    _pickle_file_name = "subtensor_vtrust"
