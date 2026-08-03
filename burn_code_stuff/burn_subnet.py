# Standard imports
import argparse
import logging
import multiprocessing
import random
import sys
import time

# Bittensor imports
import bittensor as bt
from bittensor.wallet import Wallet


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
    stream=sys.stdout,
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

        # Parse the args.
        config = parser.parse_args()

        # Hard-code Rizzo wallet
        config.wallet_name = "RizzoNetwork"
        config.wallet_hotkey = f"rz{config.netuid:03d}"

        return config

    def rotate_local_subtensor(self):
        if self.config.local_subtensor is False:
            return

        self.local_subtensor_index = (self.local_subtensor_index + 1) % len(LOCAL_SUBTENSORS)

        network_name = (
            self.config.local_subtensor or LOCAL_SUBTENSORS[self.local_subtensor_index]
        )
        self.config.subtensor_network = \
            f"ws://subtensor-{network_name}.rizzo.network:9944"

    def _get_tempo_data(self, subtensor):
        curr_block = subtensor.block

        tempo = subtensor.query(
            bt.storage.SubtensorModule.Tempo,
            params=[self.config.netuid],
        )
        logger.info("Tempo: %s", tempo)

        blocks_since_last_step = subtensor.query(
            bt.storage.SubtensorModule.BlocksSinceLastStep,
            block=curr_block,
            params=[self.config.netuid],
        )

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

    def ensure_registered_and_validator_permit(self, subtensor, wallet):
        try:
            this_uid = subtensor.neurons.uid(
                hotkey_ss58=wallet.hotkey.ss58_address,
                netuid=self.config.netuid
            )
        except ValueError:
            logger.info("Not registered, wait until next epoch...")
            return None

        if this_uid is None:
            logger.info("Not registered, wait until next epoch...")
            return None

        logger.info("Validator UID: %i", this_uid)

        validator_permits = subtensor.query(
            bt.storage.SubtensorModule.ValidatorPermit,
            params=[self.config.netuid],
        )

        try:
            permit_granted = validator_permits[this_uid]
        except (IndexError, KeyError, TypeError) as e:
            logger.error("Error accessing validator permit for UID %i: %s", this_uid, e)
            return None

        logger.info("Validator Permit: %s", permit_granted)

        if permit_granted:
            return this_uid

        logger.info("No Validator Permit, wait until next epoch...")
        return None

    def get_weights_version_key(self, subtensor):
        version_key = subtensor.query(
            bt.storage.SubtensorModule.WeightsVersionKey,
            params=[self.config.netuid],
        )
        logger.info("Weights Version Key: %s", version_key)
        return version_key

    def get_mechids(self, subtensor):
        mech_count = subtensor.subnets.mechanism_count(self.config.netuid)
        if mech_count == 1:
            return [0]

        mech_split = subtensor.subnets.mechanism_emission_split(self.config.netuid)
        return sorted(range(mech_count), key=lambda m: bt.settings.U16_MAX - mech_split[m])

    def fetch_neurons(self, subtensor):
        try:
            neurons = subtensor.subnets.metagraph(self.config.netuid).neurons
        except Exception as e:
            logger.exception("Error fetching neurons: %s", e)
            return []

        if neurons is None:
            return []

        return neurons

    # TODO: Clean this method up.
    def get_burn_uid(self, subtensor, neurons):
        owner_hotkey = subtensor.query(
            bt.storage.SubtensorModule.SubnetOwnerHotkey,
            params=[self.config.netuid],
        )
        logger.info("Owner Hotkey: %s", owner_hotkey)
    
        try:
            owner_uid = subtensor.neurons.uid(
                hotkey_ss58=owner_hotkey,
                netuid=self.config.netuid
            )
        except ValueError:
            # TODO - Decide what to do here. Find the owner coldkey uid that registered the earliest?

            # logger.info("Owner hotkey not registered. Could not find owner uid.")
            # return None

            logger.info("Owner hotkey not registered, attempting fallback via owner coldkey lookup.")
            owner_coldkey = subtensor.query(
                bt.storage.SubtensorModule.SubnetOwner,
                params=[self.config.netuid],
            )
            logger.info("Owner Coldkey: %s", owner_coldkey)

            owner_neurons = [
                neuron for neuron in neurons if neuron.coldkey == owner_coldkey
            ]
            if not owner_neurons:
                logger.info("Owner coldkey not registered. Could not find owner uid.")
                return None

            oldest_owner_neuron = min(
                owner_neurons,
                key=lambda neuron: neuron.block_at_registration
            )
            owner_uid = oldest_owner_neuron.uid

        logger.info("Owner UID: %i", owner_uid)
        return owner_uid

        # I'm not sure what all it's doing here but it seems like more than necessary.
        # Simplifying this for now until/unless a subnet happens to not work.
        #
        # try:
        #     subnet_info = subtensor.get_subnet_info(self.config.netuid)
        #     owner_coldkey = getattr(subnet_info, "owner_ss58", None)
        # except Exception as e:
        #     logger.error("Error retrieving subnet info: %s", e)
        #     owner_coldkey = None

        # if owner_coldkey is None:
        #     logger.warning("Owner coldkey missing, attempting fallback via owner hotkey lookup")

        #     sn_owner_hotkey = subtensor.query_subtensor(
        #         "SubnetOwnerHotkey",
        #         params=[self.config.netuid],
        #     )
        #     logger.info("SN Owner Hotkey: %s", sn_owner_hotkey)

        #     sn_owner_uid = subtensor.get_uid_for_hotkey_on_subnet(
        #         hotkey_ss58=sn_owner_hotkey,
        #         netuid=self.config.netuid,
        #     )
        #     logger.info("SN Owner UID: %s", sn_owner_uid)

        #     owner_neuron = None
        #     owner_hotkey_str = str(sn_owner_hotkey)
        #     for neuron in neurons:
        #         neuron_hotkey = getattr(neuron, "hotkey", None) or getattr(neuron, "hotkey_ss58", None)
        #         if neuron_hotkey == owner_hotkey_str:
        #             owner_neuron = neuron
        #             break

        #     if owner_neuron is None:
        #         logger.warning("Owner neuron not found in neuron list, falling back to owner UID")
        #         return sn_owner_uid

        #     owner_coldkey = getattr(owner_neuron, "coldkey", None) or getattr(owner_neuron, "coldkey_ss58", None)
        #     if owner_coldkey is None:
        #         logger.warning("Owner coldkey missing on neuron, falling back to owner UID")
        #         return sn_owner_uid

        # owner_neurons = [
        #     neuron
        #     for neuron in neurons
        #     if (getattr(neuron, "coldkey", None) or getattr(neuron, "coldkey_ss58", None)) == owner_coldkey
        # ]

        # if not owner_neurons:
        #     logger.warning("No neurons found with owner coldkey, falling back to owner UID")
        #     sn_owner_hotkey = subtensor.query_subtensor(
        #         "SubnetOwnerHotkey",
        #         params=[self.config.netuid],
        #     )
        #     logger.info("SN Owner Hotkey: %s", sn_owner_hotkey)
        #     sn_owner_uid = subtensor.get_uid_for_hotkey_on_subnet(
        #         hotkey_ss58=sn_owner_hotkey,
        #         netuid=self.config.netuid,
        #     )
        #     logger.info("SN Owner UID: %s", sn_owner_uid)
        #     return sn_owner_uid

        # logger.info("found %i owner neurons", len(owner_neurons))
        # # The registration_block is "inf" for all neurons. Falling back to using
        # # the owner hotkey instead.
        # # # Prefer the neuron that registered earliest on the subnet.
        # # burn_candidate = min(
        # #     owner_neurons,
        # #     key=lambda neuron: getattr(neuron, "registration_block", float("inf"))
        # # )
        # sn_owner_hotkey = subtensor.query_subtensor(
        #     "SubnetOwnerHotkey",
        #     params=[self.config.netuid],
        # )
        # logger.info("SN Owner Hotkey: %s", sn_owner_hotkey)
        # sn_owner_uid = subtensor.get_uid_for_hotkey_on_subnet(
        #     hotkey_ss58=sn_owner_hotkey,
        #     netuid=self.config.netuid,
        # )
        # if sn_owner_uid is None:
        #     try:
        #         sn_owner_uid = subtensor.metagraph(self.config.netuid).coldkeys.index(owner_coldkey)
        #     except ValueError:
        #         pass  # I don't know what to do here.
        # logger.info("SN Owner UID: %s", sn_owner_uid)

        # burn_candidate = None
        # for neuron in owner_neurons:
        #     neuron_hotkey = getattr(neuron, "hotkey", None) or getattr(neuron, "hotkey_ss58", None)
        #     if neuron_hotkey == sn_owner_hotkey:
        #         burn_candidate = neuron
        #         break

        # if burn_candidate is None:
        #     logger.warning("Could not find a burn candidate, falling back to owner UID")
        #     return sn_owner_uid

        # burn_uid = getattr(burn_candidate, "uid", None)
        # if burn_uid is None:
        #     logger.warning("Burn candidate missing UID, falling back to owner UID")
        #     return sn_owner_uid

        # logger.info("Selected burn UID %s from owner coldkey %s", burn_uid, owner_coldkey)
        # return burn_uid

    def determine_burn_uid(self, subtensor, neurons):
        if self.config.target_uid is not None:
            logger.info("Using manually specified target UID: %s", self.config.target_uid)
            return self.config.target_uid

        burn_uid = self.get_burn_uid(subtensor, neurons)
        if burn_uid is None:
            logger.info("Could not auto-detected burn UID.")
        else:
            logger.info("Auto-detected burn UID: %s", burn_uid)
        return burn_uid

    def get_min_allowed_weights(self, subtensor):
        try:
            value = subtensor.query(
                bt.storage.SubtensorModule.MinAllowedWeights,
                params=[self.config.netuid],
            )
        except Exception as e:
            logger.error("Error fetching MinAllowedWeights: %s", e)
            return 1

        try:
            return max(int(value), 1)
        except (TypeError, ValueError):
            logger.warning("Unexpected MinAllowedWeights value: %s", value)
            return 1

    def get_max_weight_limit(self, subtensor):
        try:
            value = subtensor.query(
                bt.storage.SubtensorModule.MaxWeightsLimit,
                params=[self.config.netuid],
            )
        except Exception as e:
            logger.error("Error fetching MaxWeightsLimit: %s", e)
            return bt.settings.U16_MAX

        try:
            return max(int(value), 1)
        except (TypeError, ValueError):
            logger.warning("Unexpected MaxWeightsLimit value: %s", value)
            return bt.settings.U16_MAX

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
            neuron for neuron in neurons if neuron.validator_permit
        ]

        validator_candidates.sort(
            key=lambda neuron: neuron.total_stake.amount,
            reverse=True,
        )

        ordered_candidate_uids = []
        my_index = None
        for candidate in validator_candidates:
            candidate_uid = candidate.uid
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
                candidate_uid = neuron.uid
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
        # Commenting this. It doesn't seem like it's needed.
        # subnet_n = subtensor.query(
        #     bt.storage.SubtensorModule.SubnetworkN,
        #     params=[self.config.netuid],
        # )
        # logger.info("Subnet N: %s", subnet_n)

        min_allowed_weights = self.get_min_allowed_weights(subtensor)
        logger.info("Min Allowed Weights: %s", min_allowed_weights)

        if min_allowed_weights == 1:
            return {burn_uid: 1}

        max_weight_limit = self.get_max_weight_limit(subtensor)
        logger.info("Max Weight Limit: %s", max_weight_limit)

        epsilon_uids = self.select_epsilon_uids(
            neurons=neurons,
            this_uid=this_uid,
            burn_uid=burn_uid,
            min_allowed_weights=min_allowed_weights,
        )

        epsilon_uids = epsilon_uids[: max(min_allowed_weights - 1, 0)]
        logger.info("Epsilon UIDs: %s", epsilon_uids)

        weights = {burn_uid: max_weight_limit}
        weights.update({u: 1 for u in epsilon_uids})
        return weights

    def submit_weights(self, subtensor, wallet, weights, mechids, version_key):
        any_success = False

        for mechid in mechids:
            try:
                result = subtensor.execute(
                    bt.SetWeights(
                        netuid=self.config.netuid,
                        weights=weights,
                        mechid=mechid,
                        version_key=version_key
                    ),
                    wallet,
                    retries=2
                ).raise_for_failure()

            except bt.ChainError as exc:
                logger.error(
                    "Error setting weights on mechanism %i: %s: %s",
                    mechid, type(exc).__name__, exc)

            else:
                if not result.success:
                    logger.error("Error setting weights on mechanism %i: %s", mechid, result.message)
                else:
                    logger.info("Weights set on mechanism %i.", mechid)

                any_success |= result.success

        return any_success

    def run_burn_code(self):
        # Initialize wallet.
        # Must initialize it here rather than making it an object variable
        # when running in subprocess mode. Must run in subprocess mode to
        # reduce memory leaks due to the subtensor connection.
        wallet = Wallet(name=self.config.wallet_name, hotkey=self.config.wallet_hotkey)
        logger.info("Wallet: %s", wallet)

        # Initialize subtensor.
        with bt.Subtensor(network=self.config.subtensor_network) as subtensor:
            logger.info("Subtensor: %s", subtensor)

            # Check if registered and has validator permit
            this_uid = self.ensure_registered_and_validator_permit(subtensor, wallet)
            if this_uid is None:
                return self.get_blocks_until_next_epoch(subtensor)

            # Get the weights version key.
            version_key = self.get_weights_version_key(subtensor)

            # Get the mechids.
            mechids = self.get_mechids(subtensor)

            # Get neurons
            neurons = self.fetch_neurons(subtensor)
            if not neurons:
                logger.warning("Unable to retrieve neurons, retrying shortly...")
                return 5  # Wait 5 blocks (1 minute) before trying again.

            # Get the burn uid
            burn_uid = self.determine_burn_uid(subtensor, neurons)
            if burn_uid is None:
                return self.get_blocks_until_next_epoch(subtensor)

            # Get the weights to set
            weights = self.prepare_weight_payload(subtensor, neurons, burn_uid, this_uid)

            # Set weights
            if self.submit_weights(subtensor, wallet, weights, mechids, version_key):
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
