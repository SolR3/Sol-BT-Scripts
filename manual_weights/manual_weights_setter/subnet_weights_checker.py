# standard imports
import asyncio
import json
import random
import subprocess
import time

# bittensor imports
import bittensor
from bittensor.wallet import Wallet

# Local imports
from .common import logger


class TestWallet:
    _hotkey_addresses = {
        3: "5He5TL2hHRjU2R6MsPEwMUw4DTZnL9vszPwtCHag3vuDEjs3",
        20: "5ExaAP3ENz3bCJufTzWzs6J6dCWuhjjURT8AdZkQ5qA4As2o",
        45: "5DnNzmms8Pg7YekmHsDjJXKUMYeBG8ziM9nMj19pfiH5vs45",
        75: "5F9u6pymyXKHZWn1BSmimT9ux5LST9DRXiRHT8NQwTYpFs75",
    }

    class Hotkey:
        def __init__(self, hotkey_address):
            self.ss58_address = hotkey_address

    def __init__(self, name, hotkey):
        netuid = int(hotkey[2:])
        try:
            hotkey_address = self._hotkey_addresses[netuid]
        except KeyError:
            raise Exception(f"Can't test on subnet {netuid}.")
        self.hotkey = TestWallet.Hotkey(hotkey_address)


class SubnetWeightsChecker:
    _local_subtensors = [
        "cali",
        "candyland",
        "datacenter01",
        "la",
        "moonbase",
        "titan",
    ]

    _discord_monitor_url = (
        "https://discord.com/api/webhooks/1328849265765777468/"
        "yJg07DYWLJyiFZgZPaLGTmFEwiAu2JWW5osyjFVoqlMWT66JBbV9_FOcslvDdtibtcR0"
    )

    def __init__(self, script_name, options):
        self._script_name = script_name
        self._netuids = options.netuids
        self._updated_threshold = round(options.time_threshold * 300)  # blocks
        self._check_interval = round(options.check_interval * 3600)  # seconds
        self._interval_blocks = round(self._check_interval / 12) # blocks
        self._discord_notify = options.discord_notify

        self._wallets = {}
        for netuid in self._netuids:
            self._wallets[netuid] = Wallet(  # TestWallet(
                name="RizzoNetwork", hotkey=f"rz{netuid:03d}",
            )

        random.seed()
        self._local_subtensor_index = random.randint(0, len(self._local_subtensors) - 1)
        self._expected_updated_values = dict(
            [(n, self._updated_threshold) for n in self._netuids]
        )

        self._run()

    def _log_info(self, *args):
        logger.info(*args)

    def _log_error(self, *args):
        logger.error(*args)

    def _log_warning(self, *args):
        logger.warning(*args)

    def _log_debug(self, *args):
        logger.debug(*args)

    def _run(self):
        while True:
            start_time = int(time.time())
            asyncio.run(self._async_run())

            elapsed_time = int(time.time()) - start_time
            sleep_interval = self._check_interval - elapsed_time
            if sleep_interval > 0:
                self._log_info("")
                self._log_info("Sleeping for %i seconds.", sleep_interval)
                time.sleep(sleep_interval)
            else:
                # Shouldn't ever get here
                self._log_warning(
                    "Elapsed time (%i seconds) is greater than "
                    "check interval (%i seconds).",
                    elapsed_time, self._check_interval
                )

    async def _async_run(self):
        self._log_info("")
        self._log_info(
            "Checking updated values and determining whether to manually set weights."
        )
        self._log_info("")

        netuids = []
        for netuid in self._netuids:
            expected_updated = self._expected_updated_values[netuid]
            if expected_updated >= self._updated_threshold:
                netuids.append(netuid)
            else:
                self._expected_updated_values[netuid] += self._interval_blocks
                self._log_info(
                    "Not checking subnet %i. Expected updated value %i < %i",
                    netuid, expected_updated, self._updated_threshold)

        if not netuids:
            return

        # Loop until we get a subtensor connection
        while True:
            self._local_subtensor_index = \
                (self._local_subtensor_index + 1) % len(self._local_subtensors)
            network_name = self._local_subtensors[self._local_subtensor_index]
            network = f"ws://subtensor-{network_name}.rizzo.network:9944"

            self._log_info("")
            self._log_info("Connecting to subtensor network: %s", network)
            try:
                async with bittensor.Subtensor(network=network) as subtensor:
                    await self._check_and_set_weights(subtensor, netuids)
                break
            except Exception as err:
                self._log_error("")
                self._log_error("Subtensor connection failed on '%s'", network)
                self._log_error("%s: %s", type(err).__name__, err)
                self._log_error("")
                self._log_error("Rotating subtensors and trying again.")
                time.sleep(1)

    async def _check_and_set_weights(self, subtensor, netuids):
        # Get the block to pass to async calls so everything is in sync
        # and sync the metagraph for each netuid.
        block = await subtensor.block()
        metagraphs = await asyncio.gather(
            *[subtensor.subnets.metagraph(netuid, block=block) for netuid in netuids]
        )

        for ni, netuid in enumerate(netuids):
            self._log_info("")
            self._log_info("Checking subnet %i", netuid)

            metagraph = metagraphs[ni]
            rizzo_hotkey = self._wallets[netuid].hotkey.ss58_address
            rizzo_uid = self._get_rizzo_uid(metagraph, rizzo_hotkey)
            if rizzo_uid is None:
                self._log_warning("Rizzo validator is not running on subnet %i.", netuid)
                continue

            rizzo_updated = metagraph.block - metagraph.neurons[rizzo_uid].last_update
            self._log_info("Rizzo Updated is %i blocks.", rizzo_updated)

            # If the rizzo updated value is greater than the weights threshold
            # then manually set weights.
            if rizzo_updated >= self._updated_threshold:
                self._log_info("Updated value %i >= %i", rizzo_updated, self._updated_threshold)
                self._log_info("Manually setting weights on subnet %i.", netuid)
                await self._set_weights(subtensor, netuid, rizzo_uid, rizzo_updated)
            else:
                self._expected_updated_values[netuid] = \
                    rizzo_updated + self._interval_blocks
                self._log_info("Updated value %i < %i", rizzo_updated, self._updated_threshold)
                self._log_info("Not setting weights on subnet %i.", netuid)

    def _get_rizzo_uid(self, metagraph, rizzo_hotkey):
        try:
            uid = metagraph.hotkeys.index(rizzo_hotkey)
        except ValueError:
            self._log_warning(
                "Rizzo hotkey %s is not found on subnet %i.", rizzo_hotkey, metagraph.netuid
            )
            return None

        if not metagraph.neurons[uid].validator_permit:
            self._log_warning(
                "Rizzo hotkey %s does not have a validator permit on subnet %i.",
                rizzo_hotkey, metagraph.netuid
            )
            return None

        return uid

    async def _set_weights(self, subtensor, netuid, rizzo_uid, rizzo_updated):
        # Get weights.
        all_weights = await subtensor.weights.weights(netuid=netuid)
        if rizzo_uid in all_weights:
            self._log_info("Using previous weights.")
            weights = all_weights[rizzo_uid]
        else:
            self._log_info("No previous weights are set. Determining burn weights.")
            weights = await self._get_burn_weights(subtensor, netuid)

        if not weights:
            self._log_error(
                "Could not determine weights to set on subnet %i. "
                "Not setting weights.", netuid
            )
            self._send_monitor_notification(
                f"Failed to manually set weights on subnet {netuid}: "
                "Could not determine weights to set."
            )
            return

        self._log_info("Setting the following weights:")
        self._log_info("    weights = %s", weights)

        # Get the weights version key.
        version_key = await subtensor.query(
            bittensor.storage.SubtensorModule.WeightsVersionKey,
            params=[netuid],
        )
        self._log_debug("Subnet %i Weights Version Key: %i", netuid, version_key)

        # Set weights.
        try:
            result = await subtensor.execute(
                bittensor.SetWeights(
                    netuid=netuid,
                    weights=weights,
                    version_key=version_key
                ),
                self._wallets[netuid],
                retries=2
            )
            result.raise_for_failure()

        except bittensor.ChainError as exc:
            self._expected_updated_values[netuid] += self._interval_blocks
            self._log_error(
                "Error setting weights on subnet %i: %s: %s",
                netuid, type(exc).__name__, exc
            )
            self._send_monitor_notification(
                f"Failed to manually set weights on subnet {netuid}: {type(exc).__name__}: {exc}"
            )

        if not result.success:
            self._expected_updated_values[netuid] += self._interval_blocks
            self._log_error(
                "Error setting weights on subnet %i: %s", netuid, result.message
            )
            self._send_monitor_notification(
                f"Failed to manually set weights on subnet {netuid}: {result.message}"
            )

        else:
            self._expected_updated_values[netuid] = self._interval_blocks
            self._log_info("Weights successfully set on subnet %i.", netuid)
            self._send_monitor_notification(
                f"Manually set weights on subnet {netuid} - Updated value was {rizzo_updated}"
            )

    async def _get_burn_weights(self, subtensor, netuid):
        # Get the subtensor owner hotkey
        owner_hotkey = await subtensor.query(
            bittensor.storage.SubtensorModule.SubnetOwnerHotkey,
            params=[netuid],
        )
        self._log_debug("Subnet %i Owner Hotkey: %s", netuid, owner_hotkey)

        # Get the UID of this hotkey
        try:
            owner_uid = await subtensor.neurons.uid(
                hotkey_ss58=owner_hotkey,
                netuid=netuid
            )
        except ValueError:
            self._log_error(
                "Could not find owner uid from owner hotkey %s on subnet %i",
                owner_hotkey, netuid
            )
            return None

        self._log_debug("Subnet %i Owner UID: %i", netuid, owner_uid)

        weights = {owner_uid: 1}

        return weights

    def _send_monitor_notification(self, message):
        if not self._discord_notify:
            self._log_info("Not sending discord monitor notification.")
            return

        text = f"{self._script_name}: " + message
        payload = json.dumps({"content": text})
        monitor_cmd = [
            "curl", "-H", "Content-Type: application/json",
            "-d", payload, self._discord_monitor_url
        ]
        monitor_cmd_str = " ".join(monitor_cmd)
        self._log_info("Running command: '%s'", monitor_cmd_str)
        try:
            subprocess.run(monitor_cmd, check=True)
        except subprocess.CalledProcessError as exc:
            self._log_error("Failed to send discord monitor notification.")
            self._log_error("'%s' command failed with error %s", monitor_cmd_str, exc)
        else:
            self._log_info("Discord monitor notification successfully sent.")
