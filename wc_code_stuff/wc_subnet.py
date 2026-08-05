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

# vTrust precision factor
EPSILON = 1e-5

# Seconds per block
BLOCK_TIME = 12

# Weight setting interval in blocks
INTERVAL = 120

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


class WCValidator:
    def __init__(self):
        self.config = self.get_config()

        # Randomize local subtensor index.
        random.seed()
        self.local_subtensor_index = random.randint(0, len(LOCAL_SUBTENSORS) - 1)

    def get_config(self):
        # Set up the configuration parser.
        parser = argparse.ArgumentParser(
            description="Subnet Validator",
            usage="python3 wc_subnet.py <command> [options]",
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

        # Add optional source_uid argument
        run_command_parser.add_argument(
            "--source-uid",
            type=int,
            default=None,
            help="Manually specify the UID to copy weights from (overrides auto-detection)."
        )

        run_command_parser.add_argument(
            "--local-subtensor",
            nargs="?",
            default=False,
            help="Use the specified local subtensor (i.e. la, cali, titan, etc.). "
                 "List the flag without a value to rotate between all local "
                 "subtensors. When not specified, use the 'finney' network subtensor."
        )

        run_command_parser.add_argument(
            "--dryrun",
            action="store_true",
            help="Use the specified local subtensor (i.e. la, cali, titan, etc.). "
                 "List the flag without a value to rotate between all local "
                 "subtensors. When not specified, use the 'finney' network subtensor."
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

        self.local_subtensor_index = \
                (self.local_subtensor_index + 1) % len(LOCAL_SUBTENSORS)

        network_name = (
            self.config.local_subtensor or LOCAL_SUBTENSORS[self.local_subtensor_index]
        )
        self.config.subtensor_network = \
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

    def get_next_perfect_weight_setting_opportunity(self, subtensor, start_block):
        blocks_to_wait = start_block + INTERVAL - subtensor.block
        logger.info("Blocks until next weight set, %s...", blocks_to_wait)
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
        if not permit_granted:
            logger.info("No Validator Permit, wait until next epoch...")

        # this_uid should never be 0 but just to be safe
        return this_uid if permit_granted else None

    def get_weights_version_key(self, subtensor):
        version_key = subtensor.query_subtensor(
            "WeightsVersionKey",
            params=[self.config.netuid],
        ).value
        logger.info("Weights Version Key: %s", version_key)
        return version_key

    # TODO - Make this better.
    def get_wc_uid(self, metagraph, this_uid):
        # Get all validators that aren't us
        vali_uids = metagraph.uids[metagraph.validator_permit]
        vali_uids = vali_uids[vali_uids != this_uid]
        if not vali_uids.size:
            logger.warning("There are no other validators on this subnet.")
            return None

        # Filter validators to those with 1.0 vT
        vali_vtrust = metagraph.Tv[vali_uids]
        vali_uids = vali_uids[vali_vtrust >= (1.0 - EPSILON)]
        if not vali_uids.size:
            logger.warning("There are no validators with 1.0 vTrust.")
            return None

        # Filter validators to those with low updated values 
        vali_updated = metagraph.block - metagraph.last_update[vali_uids]
        vali_uids = vali_uids[vali_updated <= 720]  # two tempos
        if not vali_uids.size:
            logger.warning("There are no validators with updated value <= 720.")
            return None

        # Select the validator with the highest stake
        vali_stake = metagraph.total_stake[vali_uids]
        max_stake = max(vali_stake)
        wc_uid = int(vali_uids[vali_stake == max_stake][0])

        return wc_uid

    def determine_wc_uid(self, metagraph, this_uid):
        if self.config.source_uid is not None:
            logger.info("Using manually specified source UID: %s", self.config.source_uid)
            return self.config.source_uid

        wc_uid = self.get_wc_uid(metagraph, this_uid)
        if wc_uid is None:
            logger.warning("Could not determine WC UID. Not setting weights.")
        else:
            logger.info("Auto-detected WC UID: %s", wc_uid)
        return wc_uid

    def prepare_weight_payload(self, metagraph, wc_uid):        
        wc_uid_weights = metagraph.weights[wc_uid]
        uids = metagraph.uids[wc_uid_weights > 0]
        weights = wc_uid_weights[uids]

        logger.info("Weights UIDs: %s", uids)
        logger.info("Weights: %s", weights)

        return uids, weights

    def submit_weights(self, subtensor, wallet, uids, weights, version_key):
        success, message = subtensor.set_weights(
            wallet,
            self.config.netuid,
            uids,
            weights,
            version_key=version_key,
            wait_for_inclusion=True,
            wait_for_finalization=True,
        )
        if not success:
            logger.error("Error setting weights: %s", message)
        else:
            logger.info("Weights set successfully.")

        return success

    def run_wc_code(self):
        # Initialize wallet.
        # Must initialize it here rather than making it an object variable
        # when running in subprocess mode. Must run in subprocess mode to
        # reduce memory leaks due to the subtensor connection.
        wallet = Wallet(name=self.config.wallet_name, hotkey=self.config.wallet_hotkey)
        logger.info("Wallet: %s", wallet)

        # Initialize subtensor.
        with bt.Subtensor(network=self.config.subtensor_network) as subtensor:
            logger.info("Subtensor: %s", subtensor)

            # Check if registered.
            if not self.check_registration(subtensor, wallet):
                return self.get_blocks_until_next_epoch(subtensor)

            # Check Validator Permit
            this_uid = self.ensure_validator_permit(subtensor, wallet)
            if this_uid is None:
                return self.get_blocks_until_next_epoch(subtensor)

            # Get the weights version key.
            version_key = self.get_weights_version_key(subtensor)

            # Get the metagraph to determine wc uid and weights
            metagraph = subtensor.metagraph(self.config.netuid, lite=False)

            # Get the wc uid
            wc_uid = self.determine_wc_uid(metagraph, this_uid)
            if wc_uid is None:
                return self.get_blocks_until_next_epoch(subtensor)

            # Get the weights to set
            uids, weights = self.prepare_weight_payload(metagraph, wc_uid)

            # Get the current block to use after setting weights when determining
            # the next block for setting weights.
            start_block = subtensor.block

            # Set weights
            if self.config.dryrun:
                logger.info("DRYRUN: Not setting weights.")
                return self.get_next_perfect_weight_setting_opportunity(subtensor, start_block)

            if self.submit_weights(subtensor, wallet, uids, weights, version_key):
                return self.get_next_perfect_weight_setting_opportunity(subtensor, start_block)
            else:
                return self.get_blocks_until_next_epoch(subtensor)

    def run_in_subprocess(self):
        wait_blocks = self.run_wc_code()
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
    validator = WCValidator()
    validator.run()
