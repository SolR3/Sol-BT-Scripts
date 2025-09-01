import time
import argparse
import sys

import bittensor as bt
from bittensor_wallet import Wallet

# =========================
# Params you can edit (top-level defaults)
# =========================
# If you set DEFAULT_NETUID to an integer, --netuid becomes optional.
# Leave it as None to keep --netuid required.
DEFAULT_NETUID: int | None = None

# Optionally pin a specific UID to burn to. Leave as None for auto-detection.
DEFAULT_TARGET_UID: int | None = None

# Blocks between weight sets (e.g., 360 * 2 == 2 epochs on many subnets)
DEFAULT_SET_WEIGHTS_INTERVAL: int = 720

# Optional wallet defaults; if provided, they become the fallback for CLI
DEFAULT_WALLET_NAME: str | None = "RizzoNetwork"          # e.g., "RizzoNetwork"
DEFAULT_WALLET_HOTKEY: str | None = None        # e.g., "rz123"

# Optional network defaults; either set NETWORK (like "finney") or a chain endpoint
DEFAULT_NETWORK: str | None = "finney"              # e.g., "finney"
DEFAULT_CHAIN_ENDPOINT: str | None = None       # e.g., "ws://127.0.0.1:9944"

# Sleep time per block (seconds)
BLOCK_TIME = 12
# =========================

# Local subtensors to rotate
LOCAL_SUBTENSORS = [
    "cali",
    "candyland",
    "datacenter01",
    "la",
    "moonbase",
    "titan",
]


class TempValidator:
    def __init__(self):
        self.config = self.get_config()
        self._apply_top_defaults(self.config)

        # Double-check that netuid is specified (after applying top defaults)
        if getattr(self.config, "command", None) == "run" and not hasattr(self.config, "netuid"):
            print("Error: --netuid is required but not specified (and no DEFAULT_NETUID set at top).")
            sys.exit(1)

        # Initialize wallet.
        self.wallet = Wallet(config=self.config)
        print(f"Wallet: {self.wallet}")

        self.local_subtensor_index = -1

    def _apply_top_defaults(self, config):
        """
        Apply the top-of-file parameter defaults into the parsed config
        (without removing the ability to override via CLI).
        """
        # Netuid / target uid / interval
        if not getattr(config, "netuid", None) and DEFAULT_NETUID is not None:
            config.netuid = DEFAULT_NETUID

        # target_uid may not exist yet; only set if not provided on CLI
        if not hasattr(config, "target_uid"):
            config.target_uid = DEFAULT_TARGET_UID
        elif config.target_uid is None and DEFAULT_TARGET_UID is not None:
            config.target_uid = DEFAULT_TARGET_UID

        # Ensure set_weights_interval has a sensible default
        if not hasattr(config, "set_weights_interval") or config.set_weights_interval is None:
            config.set_weights_interval = DEFAULT_SET_WEIGHTS_INTERVAL

        # Wallet defaults
        if hasattr(config, "wallet"):
            if (getattr(config.wallet, "name", None) in (None, "", "default")) and (DEFAULT_WALLET_NAME is not None):
                config.wallet.name = DEFAULT_WALLET_NAME
            if (getattr(config.wallet, "hotkey", None) in (None, "", "default")):
                if (DEFAULT_WALLET_HOTKEY is not None):
                    config.wallet.hotkey = DEFAULT_WALLET_HOTKEY
                else:
                    # Find the rizzo hotkey from the netuid
                    config.wallet.hotkey = f"rz{config.netuid:03d}"

        # Subtensor network/endpoint defaults
        if hasattr(config, "subtensor"):
            # Prefer explicit endpoint if provided at top
            if (getattr(config.subtensor, "chain_endpoint", None) in (None, "")) and (DEFAULT_CHAIN_ENDPOINT is not None):
                config.subtensor.chain_endpoint = DEFAULT_CHAIN_ENDPOINT
            # Otherwise, fall back to network name
            if (getattr(config.subtensor, "network", None) in (None, "")) and (DEFAULT_NETWORK is not None):
                config.subtensor.network = DEFAULT_NETWORK

    def get_config(self):
        # Set up the configuration parser.
        parser = argparse.ArgumentParser(
            description="Subnet Validator",
            usage="python3 burn_subnet.py <command> [options]",
            add_help=True,
        )
        command_parser = parser.add_subparsers(dest="command")
        run_command_parser = command_parser.add_parser(
            "run", help="""Run the validator"""
        )

        # Adds required argument for netuid with no default unless DEFAULT_NETUID is set
        run_command_parser.add_argument(
            "--netuid",
            type=int,
            required=(DEFAULT_NETUID is None),
            default=DEFAULT_NETUID,
            help="The chain subnet uid.",
        )

        # Add optional target_uid argument
        run_command_parser.add_argument(
            "--target_uid",
            type=int,
            default=DEFAULT_TARGET_UID,
            help="Manually specify the target UID to burn weights to (overrides auto-detection)."
        )

        run_command_parser.add_argument(
            "--set_weights_interval",
            type=int,
            default=DEFAULT_SET_WEIGHTS_INTERVAL,  # 2 epochs by default
            help="The interval to set weights in blocks.",
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
            help="When specified, run weight setting in a subprocess. This should keep "
                 "the subtensor connection from hanging every once in a while."
        )

        # Adds subtensor specific arguments.
        bt.subtensor.add_args(run_command_parser)
        # Adds wallet specific arguments.
        Wallet.add_args(run_command_parser)

        # Parse the config.
        try:
            config = bt.config(parser)
        except ValueError as e:
            print(f"Error parsing config: {e}")
            sys.exit(1)

        # (We now allow DEFAULT_NETUID to satisfy the requirement, so no extra check here.)
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

    def get_burn_uid(self, subtensor):
        # Get the subtensor owner hotkey
        sn_owner_hotkey = subtensor.query_subtensor(
            "SubnetOwnerHotkey",
            params=[self.config.netuid],
        )
        print(f"SN Owner Hotkey: {sn_owner_hotkey}")

        # Get the UID of this hotkey
        sn_owner_uid = subtensor.get_uid_for_hotkey_on_subnet(
            hotkey_ss58=sn_owner_hotkey,
            netuid=self.config.netuid,
        )
        print(f"SN Owner UID: {sn_owner_uid}")

        return sn_owner_uid

    def run_burn_code(self):
        # Initialize subtensor.
        with bt.subtensor(config=self.config) as subtensor:
            print(f"Subtensor: {subtensor}")

            # Check if registered.
            registered = subtensor.is_hotkey_registered_on_subnet(
                hotkey_ss58=self.wallet.hotkey.ss58_address,
                netuid=self.config.netuid,
            )
            print(f"Registered: {registered}")

            if not registered:
                print("Not registered, skipping...")
                return

            # Check Validator Permit
            validator_permits = subtensor.query_subtensor(
                "ValidatorPermit",
                params=[self.config.netuid],
            ).value
            this_uid = subtensor.get_uid_for_hotkey_on_subnet(
                hotkey_ss58=self.wallet.hotkey.ss58_address,
                netuid=self.config.netuid,
            )
            print(f"Validator UID: {this_uid}")
            print(f"Validator Permit: {validator_permits[this_uid]}")
            if not validator_permits[this_uid]:
                print("No Validator Permit, skipping...")
                return

            # Get the weights version key.
            version_key = subtensor.query_subtensor(
                "WeightsVersionKey",
                params=[self.config.netuid],
            ).value
            print(f"Weights Version Key: {version_key}")

            # Check if manual UID is provided
            if getattr(self.config, "target_uid", None) is not None:
                burn_uid = self.config.target_uid
                print(f"Using manually specified target burn UID: {burn_uid}")
            else:
                # Get the burn UID automatically
                burn_uid = self.get_burn_uid(subtensor)
                print(f"Auto-detected burn UID: {burn_uid}")

            subnet_n = subtensor.query_subtensor(
                "SubnetworkN",
                params=[self.config.netuid],
            ).value
            print(f"Subnet N: {subnet_n}")

            # Set weights to burn UID.
            uids = [burn_uid]
            weights = [1.0]

            # Set weights.
            success, message = subtensor.set_weights(
                self.wallet,
                self.config.netuid,
                uids,
                weights,
                version_key=version_key,
                wait_for_inclusion=True,
                wait_for_finalization=True,
            )
            if not success:
                print(f"Error setting weights: {message}")
            else:
                print("Weights set.")

    def run(self):
        print(f"Running validator for subnet {self.config.netuid}...")

        while True:
            print("Running validator loop...")
            self.rotate_local_subtensor()

            if self.config.subprocess:
                args = []
                with multiprocessing.Pool(processes=1) as pool:
                    pool.apply(self.run_burn_code, args)
            else:
                self.run_burn_code()

            # Wait for next time to set weights.
            print(
                f"Waiting {self.config.set_weights_interval} blocks before next weight set..."
            )
            time.sleep(self.config.set_weights_interval * BLOCK_TIME)


if __name__ == "__main__":
    validator = TempValidator()

    if validator.config.subprocess:
        import multiprocessing

    validator.run()
