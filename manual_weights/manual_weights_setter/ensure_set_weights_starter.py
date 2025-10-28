# standard imports
import argparse
import json
import os
import shlex
import subprocess

# local imports
from manual_weights_setter.common import parse_ensure_set_weights_args


SCRIPT_NAME = "ensure_set_weights"


class EnsureSetWeightsStarter:
    def __init__(self, args, extra_args):
        self._add_netuids = args.add
        self._remove_netuids = args.remove
        self._extra_input_args = extra_args

        self._process_args = argparse.Namespace()
        self._existing_process = None
        self._script_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            SCRIPT_NAME
        )

        # Find the existing ensure_set_weights pm2 process. If an
        # existing process exists then get the existing args for it.
        self._find_existing_process()

        # Add and remove netuids to the existing process args based on the
        # --add and --remove arguments passed to this command. Also update the 
        # process args with any extra arguments passed to this command.
        self._update_process_args()

        # Delete the existing pm2 process and start a new pm2 process.
        self._restart_process()
        self._save_pm2()

    def _find_existing_process(self):
        """ Find the existing ensure_set_weights pm2 process. If an
        existing process exists then get the existing args for it."""

        # Loop through each pm2 process to find and existing ensure_set_weights process. 
        process = subprocess.run(["pm2", "jlist"], stdout=subprocess.PIPE)
        pm2_output = json.loads(process.stdout)
        for pm2_process in pm2_output:
            pm2_env = pm2_process["pm2_env"]

            script_path = pm2_env["pm_exec_path"]
            script_name = os.path.basename(script_path)
            if script_name != SCRIPT_NAME:
                continue

            # The existing process was found. Get the current process args
            # and name so it can be safely deleted before restarting, then
            # break out of the loop.
            self._existing_process = pm2_process["name"]
            if "args" in pm2_env:
                script_args = pm2_env["args"]
                self._process_args = \
                    parse_ensure_set_weights_args(script_args)
            break

    def _update_process_args(self):
        """ Add and remove netuids to the existing process args based on the
        --add and --remove arguments passed to this command. Also update the 
        process args with any extra arguments passed to this command."""
        if not hasattr(self._process_args, "netuids"):
            self._process_args.netuids = []

        # Add --add netuids
        for netuid in self._add_netuids:
            if netuid not in self._process_args.netuids:
                self._process_args.netuids.append(netuid)
            else:
                print(f"Netuid {netuid} is already running. Skipping.")

        # Remove --remove netuids
        for netuid in self._remove_netuids:
            if netuid in self._process_args.netuids:
                self._process_args.netuids.remove(netuid)
            else:
                print(f"Netuid {netuid} is not running. Skipping.")

        # Sort the netuids so it's easier to see which netuids are running
        self._process_args.netuids = sorted(self._process_args.netuids)

        # Add extra command line args. --netuids is a required argument so
        # add a dummy netuid arg so the parser doesn't fail. It needs to be
        # done this way rather than just appending self._extra_input_args so
        # that existing process args are replaced.
        extra_args = parse_ensure_set_weights_args(
            self._extra_input_args + ["--netuids", "0"]
        )
        for arg, value in extra_args.__dict__.items():
            # Special case for --skip-discord-notify arg
            if arg == "discord_notify":
                if value is False:
                    setattr(self._process_args, arg, value)
                continue
            if arg != "netuids" and value is not None:
                setattr(self._process_args, arg, value)

    def _restart_process(self):
        """ Delete the existing pm2 process and start a new pm2 process."""
        # Delete the existing pm2 process if it exists
        if self._existing_process:
            pm2_stop_cmd = ["pm2", "delete", self._existing_process]
            print("")
            print(f"Running command: {shlex.join(pm2_stop_cmd)}")
            print("")
            try:
                subprocess.run(pm2_stop_cmd, check=True)
            except subprocess.CalledProcessError as exc:
                print(f"ERROR: Command failed with error: {exc}")
                return

        if not self._process_args.netuids:
            print("")
            print(f"There are no netuids to run. Not running {SCRIPT_NAME} process.")
            print("")
            return

        # Start the new pm2 process
        pm2_start_cmd = [
            "pm2", "start", "--interpreter", "python3", self._script_path, "--"
        ]
        for arg, value in self._process_args.__dict__.items():
            if value is None:
                continue

            # Special case for --skip-discord-notify arg
            if arg == "discord_notify":
                if value is False:
                    pm2_start_cmd.extend(["--skip-discord-notify"])
                continue

            command_line_arg = ["--" + arg.replace("_", "-")]
            if isinstance(value, list):
                command_line_arg.extend(str(v) for v in value)
            else:
                command_line_arg.append(str(value))
            pm2_start_cmd.extend(command_line_arg)

        print("")
        print(f"Running command: {shlex.join(pm2_start_cmd)}")
        print("")
        try:
            subprocess.run(pm2_start_cmd, check=True)
        except subprocess.CalledProcessError as exc:
            print(f"ERROR: Command failed with error: {exc}")

    def _save_pm2(self):
        pm2_save_cmd = ["pm2", "save"]
        pm2_save_cmd_str = shlex.join(pm2_save_cmd)
        print("")
        print(f"Running command:\n{pm2_save_cmd_str}")
        print("")
        try:
            subprocess.run(pm2_save_cmd, check=True)
        except subprocess.CalledProcessError as exc:
            print(f"\nERROR: Command failed with error: {exc}")
