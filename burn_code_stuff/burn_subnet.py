# Standard imports
import argparse
import logging
import multiprocessing
import random
import sys
import time

# Bittensor imports
import bittensor as bt
from bittensor_wallet import Wallet


# Constants

# Seconds per block
BLOCK_TIME = 12

# The number of blocks before the end of the tempo should the weights be set
DELTA = 9

# Local subtensors to rotate
LOCAL_SUBTENSORS = [
    "cali",
    "candyland",
    "datacenter01",
    "la",
    "moonbase",
    "titan",
]


# Create logger
logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=logging.INFO,
    #level=logging.DEBUG,
    format="%(asctime)sZ %(levelname)s %(message)s",
)

logger = logging.getLogger(__name__)


# Create Mulitprocessing queue
mp_queue = multiprocessing.Queue()


class BurnValidator:
    def __init__(self):
        self.config = self.get_config()

        # Randomize local subtensor index.
        random.seed()
        self.local_subtensor_index = random.randint(0, len(LOCAL_SUBTENSORS) - 1)

    def get_config(self):
        # Set up the configuration parser.
        parser = argparse.ArgumentParser(
            description="Subnet Validator",
            usage="python3 burn_subnet.py <command> [options]",
            add_help=True,
        )
        command_parser = parser.add_subparsers(dest="command")
        run_command_parser = command_parser.add_parser(
            "run",
            help="""Run the validator""",
        )

        # Adds required argument for netuid with no default
        run_command_parser.add_argument(
            "--netuid",
            type=int,
            required=True,
            help="The chain subnet uid.",
        )

        # Add optional target_uid argument
        run_command_parser.add_argument(
            "--target_uid",
            type=int,
            default=None,
            help="Manually specify the target UID to burn weights to (overrides auto-detection)."
        )

        run_command_parser.add_argument(
            "--set_weights_interval",
            type=int,
            help="Dummy arg. No longer used."
        )

        run_command_parser.add_argument(
            "--local-subtensor",
            nargs="?",
            default=False,
            help="Use the specified local subtensor (i.e. la, cali, titan, etc.). "
                 "List the flag without a value to rotate between all local "
                 "subtensors. When not specified, use the 'finney' network subtensor."
        )

        parser.add_argument(
            "--subprocess",
            action="store_true",
            help="Dummy arg. No longer used."
        )

        # Adds subtensor specific arguments.
        bt.Subtensor.add_args(run_command_parser)

        # Adds wallet specific arguments.
        Wallet.add_args(run_command_parser)

        # Parse the config.
        try:
            config = bt.Config(parser)
        except ValueError as e:
            logger.error("Error parsing config: %s", e)
            sys.exit(1)

        # Hard-code Rizzo wallet
        config.wallet.name = "RizzoNetwork"
        config.wallet.hotkey = f"rz{config.netuid:03d}"

        return config

    def rotate_local_subtensor(self):
        if self.config.local_subtensor is False:
            return

        self.local_subtensor_index = \
                (self.local_subtensor_index + 1) % len(LOCAL_SUBTENSORS)

        network_name = (
            self.config.local_subtensor or LOCAL_SUBTENSORS[self.local_subtensor_index]
        )
        self.config.subtensor.network = \
            f"ws://subtensor-{network_name}.rizzo.network:9944"

    def _get_tempo_data(self, subtensor):
        curr_block = subtensor.get_current_block()

        tempo = subtensor.query_subtensor(
            "Tempo",
            params=[self.config.netuid],
        ).value
        logger.info("Tempo: %s", tempo)

        blocks_since_last_step = subtensor.query_subtensor(
            "BlocksSinceLastStep",
            block=curr_block,
            params=[self.config.netuid],
        ).value

        logger.info("Blocks Since Last Step: %s", blocks_since_last_step)
        return tempo, blocks_since_last_step

    def get_blocks_until_next_epoch(self, subtensor):
        tempo, blocks_since_last_step = self._get_tempo_data(subtensor)
        blocks_until_epoch = tempo - blocks_since_last_step
        logger.info("Blocks until next epoch, %s...", blocks_until_epoch)
        return blocks_until_epoch

    def get_next_perfect_weight_setting_opportunity(self, subtensor):
        tempo, blocks_since_last_step = self._get_tempo_data(subtensor)
        remaining_blocks_until_epoch = tempo - blocks_since_last_step

        blocks_to_wait = remaining_blocks_until_epoch - DELTA
        if blocks_to_wait < 1:
            # the moment has passed, it's too late to submit weights . Wait until the next one.
            blocks_to_wait += tempo
        elif blocks_to_wait <= DELTA:
            # oh, now is the time to act!
            return 0

        logger.info("The next perfect weight setting opportunity is in %s blocks...", blocks_to_wait)
        return blocks_to_wait


    def check_registration(self, subtensor, wallet):
        registered = subtensor.is_hotkey_registered_on_subnet(
            hotkey_ss58=wallet.hotkey.ss58_address,
            netuid=self.config.netuid,
        )
        logger.info("Registered: %s", registered)

        if not registered:
            logger.info("Not registered, wait until next epoch...")
            return False

        return True

    def ensure_validator_permit(self, subtensor, wallet):
        validator_permits = subtensor.query_subtensor(
            "ValidatorPermit",
            params=[self.config.netuid],
        ).value
        this_uid = subtensor.get_uid_for_hotkey_on_subnet(
            hotkey_ss58=wallet.hotkey.ss58_address,
            netuid=self.config.netuid,
        )
        logger.info("Validator UID: %s", this_uid)

        try:
            permit_granted = validator_permits[this_uid]
        except (IndexError, KeyError, TypeError) as e:
            logger.error("Error accessing validator permit for UID %s: %s", this_uid, e)
            return None

        logger.info("Validator Permit: %s", permit_granted)

        if permit_granted:
            return this_uid

        logger.info("No Validator Permit, wait until next epoch...")
        return None

    def get_weights_version_key(self, subtensor):
        version_key = subtensor.query_subtensor(
            "WeightsVersionKey",
            params=[self.config.netuid],
        ).value
        logger.info("Weights Version Key: %s", version_key)
        return version_key

    def fetch_neurons(self, subtensor):
        try:
            neurons = subtensor.neurons(netuid=self.config.netuid)
        except Exception as e:
            logger.exception("Error fetching neurons: %s", e)
            return []

        if neurons is None:
            return []

        return neurons

    def get_burn_uid(self, subtensor, neurons):
        try:
            subnet_info = subtensor.get_subnet_info(self.config.netuid)
            owner_coldkey = getattr(subnet_info, "owner_ss58", None)
        except Exception as e:
            logger.error("Error retrieving subnet info: %s", e)
            owner_coldkey = None

        if owner_coldkey is None:
            logger.warning("Owner coldkey missing, attempting fallback via owner hotkey lookup")

            sn_owner_hotkey = subtensor.query_subtensor(
                "SubnetOwnerHotkey",
                params=[self.config.netuid],
            )
            logger.info("SN Owner Hotkey: %s", sn_owner_hotkey)

            sn_owner_uid = subtensor.get_uid_for_hotkey_on_subnet(
                hotkey_ss58=sn_owner_hotkey,
                netuid=self.config.netuid,
            )
            logger.info("SN Owner UID: %s", sn_owner_uid)

            owner_neuron = None
            owner_hotkey_str = str(sn_owner_hotkey)
            for neuron in neurons:
                neuron_hotkey = getattr(neuron, "hotkey", None) or getattr(neuron, "hotkey_ss58", None)
                if neuron_hotkey == owner_hotkey_str:
                    owner_neuron = neuron
                    break

            if owner_neuron is None:
                logger.warning("Owner neuron not found in neuron list, falling back to owner UID")
                return sn_owner_uid

            owner_coldkey = getattr(owner_neuron, "coldkey", None) or getattr(owner_neuron, "coldkey_ss58", None)
            if owner_coldkey is None:
                logger.warning("Owner coldkey missing on neuron, falling back to owner UID")
                return sn_owner_uid

        owner_neurons = [
            neuron
            for neuron in neurons
            if (getattr(neuron, "coldkey", None) or getattr(neuron, "coldkey_ss58", None)) == owner_coldkey
        ]

        if not owner_neurons:
            logger.warning("No neurons found with owner coldkey, falling back to owner UID")
            sn_owner_hotkey = subtensor.query_subtensor(
                "SubnetOwnerHotkey",
                params=[self.config.netuid],
            )
            logger.info("SN Owner Hotkey: %s", sn_owner_hotkey)
            sn_owner_uid = subtensor.get_uid_for_hotkey_on_subnet(
                hotkey_ss58=sn_owner_hotkey,
                netuid=self.config.netuid,
            )
            logger.info("SN Owner UID: %s", sn_owner_uid)
            return sn_owner_uid

        logger.info("found %i owner neurons", len(owner_neurons))
        # Prefer the neuron that registered earliest on the subnet.
        burn_candidate = min(
            owner_neurons,
            key=lambda neuron: getattr(neuron, "registration_block", float("inf"))
        )

        burn_uid = getattr(burn_candidate, "uid", None)
        if burn_uid is None:
            logger.warning("Burn candidate missing UID, falling back to owner UID")
            return sn_owner_uid

        logger.info("Selected burn UID %s from owner coldkey %s", burn_uid, owner_coldkey)
        return burn_uid

    def determine_burn_uid(self, subtensor, neurons):
        if self.config.target_uid is not None:
            logger.info("Using manually specified target UID: %s", self.config.target_uid)
            return self.config.target_uid

        burn_uid = self.get_burn_uid(subtensor, neurons)
        logger.info("Auto-detected burn UID: %s", burn_uid)
        return burn_uid

    def get_min_allowed_weights(self, subtensor):
        try:
            response = subtensor.query_subtensor(
                "MinAllowedWeights",
                params=[self.config.netuid],
            )
        except Exception as e:
            logger.error("Error fetching MinAllowedWeights: %s", e)
            return 1

        value = getattr(response, "value", response)
        try:
            return max(int(value), 1)
        except (TypeError, ValueError):
            logger.warning("Unexpected MinAllowedWeights value: %s", value)
            return 1

    def get_max_weight_limit(self, subtensor):
        try:
            response = subtensor.query_subtensor(
                "MaxWeightsLimit",
                params=[self.config.netuid],
            )
        except Exception as e:
            logger.error("Error fetching MaxWeightsLimit: %s", e)
            return 65535

        value = getattr(response, "value", response)
        try:
            return max(int(value), 1)
        except (TypeError, ValueError):
            logger.warning("Unexpected MaxWeightsLimit value: %s", value)
            return 65535

    def select_epsilon_uids(self, neurons, this_uid, burn_uid, min_allowed_weights):
        epsilon_target = max(min_allowed_weights - 1, 0)
        if epsilon_target <= 0:
            return []

        epsilon_uids = []
        excluded = {burn_uid}

        if this_uid is not None and this_uid != burn_uid:
            epsilon_uids.append(this_uid)
            excluded.add(this_uid)

        remaining_required = epsilon_target - len(epsilon_uids)
        if remaining_required <= 0:
            return epsilon_uids

        validator_candidates = [
            neuron
            for neuron in neurons
            if getattr(neuron, "is_validator", None)
            or getattr(neuron, "validator_permit", False)
        ]

        validator_candidates.sort(
            key=lambda neuron: float(getattr(neuron, "stake", 0) or 0),
            reverse=True,
        )

        ordered_candidate_uids = []
        my_index = None
        for candidate in validator_candidates:
            candidate_uid = getattr(candidate, "uid", None)
            if candidate_uid is None or candidate_uid == burn_uid:
                continue
            if candidate_uid not in ordered_candidate_uids:
                ordered_candidate_uids.append(candidate_uid)
            if candidate_uid == this_uid and my_index is None:
                my_index = len(ordered_candidate_uids) - 1

        if not ordered_candidate_uids:
            return epsilon_uids

        candidate_count = len(ordered_candidate_uids)
        start_index = ((my_index or 0) * remaining_required) % candidate_count

        offset = 0
        while len(epsilon_uids) < epsilon_target and offset < candidate_count * 2:
            idx = (start_index + offset) % candidate_count
            candidate_uid = ordered_candidate_uids[idx]
            if candidate_uid not in excluded:
                epsilon_uids.append(candidate_uid)
                excluded.add(candidate_uid)
            offset += 1

        if len(epsilon_uids) < epsilon_target:
            for neuron in neurons:
                candidate_uid = getattr(neuron, "uid", None)
                if (
                    candidate_uid is None
                    or candidate_uid in excluded
                    or candidate_uid == burn_uid
                ):
                    continue
                epsilon_uids.append(candidate_uid)
                excluded.add(candidate_uid)
                if len(epsilon_uids) >= epsilon_target:
                    break

        return epsilon_uids

    def prepare_weight_payload(self, subtensor, neurons, burn_uid, this_uid):
        subnet_n = subtensor.query_subtensor(
            "SubnetworkN",
            params=[self.config.netuid],
        ).value
        logger.info("Subnet N: %s", subnet_n)

        min_allowed_weights = self.get_min_allowed_weights(subtensor)
        logger.info("Min Allowed Weights: %s", min_allowed_weights)

        max_weight_limit = self.get_max_weight_limit(subtensor)
        logger.info("Max Weight Limit: %s", max_weight_limit)

        if min_allowed_weights == 1:
            return [burn_uid], [1.0]

        epsilon_uids = self.select_epsilon_uids(
            neurons=neurons,
            this_uid=this_uid,
            burn_uid=burn_uid,
            min_allowed_weights=min_allowed_weights,
        )

        epsilon_uids = epsilon_uids[: max(min_allowed_weights - 1, 0)]
        logger.info("Epsilon UIDs: %s", epsilon_uids)

        uids = [burn_uid] + epsilon_uids
        weights = [max_weight_limit] + [1] * len(epsilon_uids)
        return uids, weights

    def submit_weights(self, subtensor, wallet, uids, weights, version_key):
        any_success = False

        mech_count = subtensor.get_mechanism_count(self.config.netuid)
        mech_split = subtensor.get_mechanism_emission_split(self.config.netuid)
        if len(mech_count) == 1:
            mechids = [0]
        else:
            mechids = sorted(range(mech_count), key=lambda m: 100 - mech_split[m])

        for mechid in mechids:
            success, message = subtensor.set_weights(
                wallet,
                self.config.netuid,
                uids,
                weights,
                mechid=mechid,
                version_key=version_key,
                wait_for_inclusion=True,
                wait_for_finalization=True,
            )
            if not success:
                logger.error("Error setting weights on mechanism %i: %s", mechid, message)
            else:
                logger.info("Weights set on mechanism %i.", mechid)
            any_success |= success

        return any_success

    def run_burn_code(self):
        # Initialize wallet.
        # Must initialize it here rather than making it an object variable
        # when running in subprocess mode. Must run in subprocess mode to
        # reduce memory leaks due to the subtensor connection.
        wallet = Wallet(config=self.config)
        logger.info("Wallet: %s", wallet)

        # Initialize subtensor.
        with bt.Subtensor(config=self.config) as subtensor:
            logger.info("Subtensor: %s", subtensor)

            # Check if registered.
            if not self.check_registration(subtensor, wallet):
                return self.get_blocks_until_next_epoch(subtensor)

            # Check Validator Permit
            this_uid = self.ensure_validator_permit(subtensor, wallet)
            if this_uid is None:
                return self.get_blocks_until_next_epoch(subtensor)

            # Get the weights version key.
            version_key = self.get_weights_version_key(subtensor)  # TODO: just set it to max

            # Get neurons
            neurons = self.fetch_neurons(subtensor)
            if not neurons:
                logger.warning("Unable to retrieve neurons, retrying shortly...")
                return 5  # Wait 5 blocks (1 minute) before trying again.

            # Get the burn uid
            burn_uid = self.determine_burn_uid(subtensor, neurons)

            # Get the weights to set
            uids, weights = self.prepare_weight_payload(subtensor, neurons, burn_uid, this_uid)

            # Set weights
            # TODO: should retry without ensuring vpermit again, version key etc
            if self.submit_weights(subtensor, wallet, uids, weights, version_key):
                pause = BLOCK_TIME * DELTA
                logger.info("sleeping %i seconds after setting weights", pause)
                time.sleep(pause)
            else:
                return self.get_blocks_until_next_epoch(subtensor)

            return self.get_next_perfect_weight_setting_opportunity(subtensor)

    def run_in_subprocess(self):
        wait_blocks = self.run_burn_code()
        mp_queue.put(wait_blocks)

    def run(self):
        logger.info("Running validator for subnet %s...", self.config.netuid)

        while True:
            logger.info("Running validator loop...")
            self.rotate_local_subtensor()

            args = []
            with multiprocessing.Pool(processes=1) as pool:
                pool.apply(self.run_in_subprocess, args)

            # Wait for next time to set weights.
            wait_blocks = mp_queue.get()
            logger.info(
                "Waiting %s blocks before next weight set...", wait_blocks
            )
            time.sleep(wait_blocks * BLOCK_TIME + 0.1)


if __name__ == "__main__":
    validator = BurnValidator()
    validator.run()
