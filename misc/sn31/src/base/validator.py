# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# TODO(developer): Set your name
# Copyright © 2023 <your name>

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.


import copy
import torch
import time
import asyncio
import argparse
import threading
import bittensor as bt
import sys
from typing import List
from traceback import print_exception
sys.path.insert(0, 'nsga-net')
from src.base.neuron import BaseNeuron
from src.mock import MockDendrite
from src.utils.config import add_validator_args
import pandas as pd
import os
import wandb


class BaseValidatorNeuron(BaseNeuron):
    """
    Base class for Bittensor validators. Your validator should inherit from this class.
    """

    neuron_type: str = "ValidatorNeuron"

    @classmethod
    def add_args(cls, parser: argparse.ArgumentParser):
        super().add_args(parser)
        add_validator_args(cls, parser)
        

    def __init__(self, config=None):
        super().__init__(config=config)

        # Save a copy of the hotkeys to local memory.
        self.hotkeys = copy.deepcopy(self.metagraph.hotkeys)
        self.valid_data_length = 0
        # Dendrite lets us send messages to other nodes (axons) in the network.
        if self.config.mock:
            self.dendrite = MockDendrite(wallet=self.wallet)
        else:
            self.dendrite = bt.dendrite(wallet=self.wallet)
        bt.logging.info(f"Dendrite: {self.dendrite}")

        # Set up initial scoring weights for validation
        bt.logging.info("Building validation weights.")
        self.scores = torch.zeros(
            self.metagraph.n, dtype=torch.float32, device=self.device
        )

        # Init sync with the network. Updates the metagraph.
        self.sync()
        # self.resync_metagraph()

        # Serve axon to enable external connections.
        # if not self.config.neuron.axon_off:
        #     self.serve_axon()
        # else:
        #     bt.logging.warning("axon off, not serving ip to chain.")

        # Create asyncio event loop to manage async tasks.
        self.loop = asyncio.get_event_loop()

        # Instantiate runners
        self.should_exit: bool = False
        self.is_running: bool = False
        self.thread: threading.Thread = None
        self.lock = asyncio.Lock()
        self.state_dir = 'state'
        self.state_file = 'state.csv'
        self.eval_frame = self.check_and_load_state(self.state_dir, self.state_file)
        self.archive = None #bt.subtensor(network="archive") we dont use this anymore will refactor the code later



    def check_and_load_state(self, state_dir, state_file):

        if not os.path.exists(state_dir):
            os.makedirs(state_dir)
            bt.logging.info(f"Created directory: {state_dir}")
            
        state_path = os.path.join(state_dir, state_file)
        if os.path.exists(state_path):
            self.eval_frame = pd.read_csv(state_path)
            bt.logging.info(f"Loaded state from {state_path}")
        else:
            self.eval_frame = self.create_empty_dataframe()
            bt.logging.info(f"No state file found at {state_path}, created an empty DataFrame")
        return self.eval_frame

    def save_validator_state(self):
        state_path = os.path.join(self.state_dir, self.state_file)
        bt.logging.info(f"Saving State to: {state_path}")
        self.eval_frame.to_csv(state_path, index=False)
       


    def create_empty_dataframe(self):
        columns = {
            'uid': pd.Series(dtype='int'),
            'local_model_dir': pd.Series(dtype='object'),
            'commit': pd.Series(dtype='object'),
            'commit_date': pd.Series(dtype='datetime64[ns]'),
            'eval_date': pd.Series(dtype='object'),
            'params': pd.Series(dtype='Int64'),
            'flops': pd.Series(dtype='Int64'),
            'accuracy': pd.Series(dtype='float'),
            'score': pd.Series(dtype='float'),
            'lr': pd.Series(dtype='float'),
            'evaluate': pd.Series(dtype='bool'),
            'pareto': pd.Series(dtype='bool'),
            'reward': pd.Series(dtype='bool'),
            'vali_evaluated': pd.Series(dtype='bool'),
            'hf_account': pd.Series(dtype='object'),
            'block':  pd.Series(dtype='Int64'),
            'ext_idx':  pd.Series(dtype='int'),
        }
        df = pd.DataFrame(columns)
        return df

    def serve_axon(self):
        """Serve axon to enable external connections."""

        bt.logging.info("serving ip to chain...")
        try:
            self.axon = bt.axon(wallet=self.wallet, config=self.config)

            try:
                self.subtensor.serve_axon(
                    netuid=self.config.netuid,
                    axon=self.axon,
                )
                bt.logging.info(
                    f"Running validator {self.axon} on network: {self.config.subtensor.chain_endpoint} with netuid: {self.config.netuid}"
                )
            except Exception as e:
                bt.logging.error(f"Failed to serve Axon with exception: {e}")
                pass

        except Exception as e:
            bt.logging.error(
                f"Failed to create Axon initialize with exception: {e}"
            )
            pass

    # async def concurrent_forward(self):
    #     coroutines = [
    #         self.forward()
    #         for _ in range(self.config.neuron.num_concurrent_forwards)
    #     ]
    #     await asyncio.gather(*coroutines)

    async def run(self):
        """
        Initiates and manages the main loop for the miner on the Bittensor network. The main loop handles graceful shutdown on keyboard interrupts and logs unforeseen errors.

        This function performs the following primary tasks:
        1. Check for registration on the Bittensor network.
        2. Continuously forwards queries to the miners on the network, rewarding their responses and updating the scores accordingly.
        3. Periodically resynchronizes with the chain; updating the metagraph with the latest network state and setting weights.

        The essence of the validator's operations is in the forward function, which is called every step. The forward function is responsible for querying the network and scoring the responses.

        Note:
            - The function leverages the global configurations set during the initialization of the miner.
            - The miner's axon serves as its interface to the Bittensor network, handling incoming and outgoing requests.

        Raises:
            KeyboardInterrupt: If the miner is stopped by a manual interruption.
            Exception: For unforeseen errors during the miner's operation, which are logged for diagnosis.
        """

        # Check that validator is registered on the network.
        self.sync()

        bt.logging.info(f"Validator starting at block: {self.block}")
        api_key = os.getenv('WANDB_API_KEY')
        if api_key is not None:
            # Log in to wandb using the API key from the environment variable
            wandb.login(key=api_key)
        else:
            bt.logging.error("Environment variable WANDB_API_KEY not found. Please set it before running the script.")
            return

        # This loop maintains the validator's operations until intentionally stopped.
        try:
            while True:
                bt.logging.info(f"step({self.step}) block({self.block})")

                # Run multiple forwards concurrently.
                #self.loop.run_until_complete(self.concurrent_forward())

                bt.logging.info(f"{self.forward=}")
                bt.logging.info("BEFORE self.forward() call")
                await self.forward()
                bt.logging.info("AFTER self.forward() call")

                # Check if we should exit.
                if self.should_exit:
                    bt.logging.info(f"should_exit = {self.should_exit}")
                    break
                time.sleep(5)
                # Sync metagraph and potentially set weights.
                self.sync()

                self.step += 1

        # If someone intentionally stops the validator, it'll safely terminate operations.
        except KeyboardInterrupt:
            self.axon.stop()
            bt.logging.success("Validator killed by keyboard interrupt.")
            wandb.finish()
            exit()

        # In case of unforeseen errors, the validator will log the error and continue operations.
        except Exception as err:
            bt.logging.error("Error during validation", str(err))
            bt.logging.debug(
                print_exception(type(err), err, err.__traceback__)
            )

    def _run_coroutine_in_thread(self):
        asyncio.run(self.run())
        
    def run_in_background_thread(self):
        """
        Starts the validator's operations in a background thread upon entering the context.
        This method facilitates the use of the validator in a 'with' statement.
        """
        if not self.is_running:
            bt.logging.debug("Starting validator in background thread.")
            self.should_exit = False
            self.thread = threading.Thread(target=self._run_coroutine_in_thread, daemon=True)
            self.thread.start()
            self.is_running = True
            bt.logging.debug("Started")

    def stop_run_thread(self):
        """
        Stops the validator's operations that are running in the background thread.
        """
        if self.is_running:
            bt.logging.debug("Stopping validator in background thread.")
            bt.logging.info("Setting self.should_exit = True")
            import traceback
            traceback.print_stack()
            self.should_exit = True
            self.thread.join(5)
            self.is_running = False
            bt.logging.debug("Stopped")

    def __enter__(self):
        self.run_in_background_thread()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Stops the validator's background operations upon exiting the context.
        This method facilitates the use of the validator in a 'with' statement.

        Args:
            exc_type: The type of the exception that caused the context to be exited.
                      None if the context was exited without an exception.
            exc_value: The instance of the exception that caused the context to be exited.
                       None if the context was exited without an exception.
            traceback: A traceback object encoding the stack trace.
                       None if the context was exited without an exception.
        """
        if self.is_running:
            bt.logging.debug("Stopping validator in background thread.")
            bt.logging.info("Setting self.should_exit = True")
            import traceback
            traceback.print_stack()
            self.should_exit = True
            self.thread.join(5)
            self.is_running = False
            bt.logging.debug("Stopped")

    def set_weights(self):
        """
        Sets the validator weights to the metagraph hotkeys based on the scores it has received from the miners. The weights determine the trust and incentive level the validator assigns to miner nodes on the network.
        """
        bt.logging.info("in set_weights()")
        # Check if self.scores contains any NaN values and log a warning if it does.
        if torch.isnan(self.scores).any():
            bt.logging.warning(
                f"Scores contain NaN values. This may be due to a lack of responses from miners, or a bug in your reward functions."
            )

        # Calculate the average reward for each uid across non-zero values.
        # Replace any NaN values with 0.
        raw_weights = torch.nn.functional.normalize(self.scores, p=1, dim=0)

        bt.logging.debug("raw_weights", raw_weights)
        bt.logging.debug("raw_weight_uids", self.metagraph.uids.to("cpu"))
        # Process the raw weights to final_weights via subtensor limitations.
        (
            processed_weight_uids,
            processed_weights,
        ) = bt.utils.weight_utils.process_weights_for_netuid(
            uids=self.metagraph.uids.to("cpu"),
            weights=raw_weights.to("cpu"),
            netuid=self.config.netuid,
            subtensor=self.subtensor,
            metagraph=self.metagraph,
        )
        bt.logging.debug("processed_weights", processed_weights)
        bt.logging.debug("processed_weight_uids", processed_weight_uids)

        # Convert to uint16 weights and uids.
        (
            uint_uids,
            uint_weights,
        ) = bt.utils.weight_utils.convert_weights_and_uids_for_emit(
            uids=processed_weight_uids, weights=processed_weights
        )
        bt.logging.debug("uint_weights", uint_weights)
        bt.logging.debug("uint_uids", uint_uids)
        try: 
            # Set the weights on chain via our subtensor connection.
            result, msg = self.subtensor.set_weights(
                wallet=self.wallet,
                netuid=self.config.netuid,
                uids=uint_uids,
                weights=uint_weights,
                wait_for_finalization=False,
                wait_for_inclusion=False,
                version_key=self.spec_version,
            )
            if result is True:
                bt.logging.info("set_weights on chain successfully!")
            else:
                bt.logging.error("set_weights failed", msg)
        except Exception as e:
            bt.logging.error(f"An exception occurred during set_weights: {str(e)}")

    def resync_metagraph(self):
        """Resyncs the metagraph and updates the hotkeys and moving averages based on the new metagraph."""
        bt.logging.info("resync_metagraph()")

        # Copies state of metagraph before syncing.
        previous_metagraph = copy.deepcopy(self.metagraph)

        # Sync the metagraph.
        self.metagraph.sync(subtensor=self.subtensor)

        # Check if the metagraph axon info has changed.
        if previous_metagraph.axons == self.metagraph.axons:
            return

        bt.logging.info(
            "Metagraph updated, re-syncing hotkeys, dendrite pool and moving averages"
        )
        # Zero out all hotkeys that have been replaced.
        for uid, hotkey in enumerate(self.hotkeys):
            if hotkey != self.metagraph.hotkeys[uid]:
                self.scores[uid] = 0  # hotkey has been replaced

        # Check to see if the metagraph has changed size.
        # If so, we need to add new hotkeys and moving averages.
        if len(self.hotkeys) < len(self.metagraph.hotkeys):
            # Update the size of the moving average scores.
            new_moving_average = torch.zeros((self.metagraph.n)).to(
                self.device
            )
            min_len = min(len(self.hotkeys), len(self.scores))
            new_moving_average[:min_len] = self.scores[:min_len]
            self.scores = new_moving_average

        # Update the hotkeys.
        self.hotkeys = copy.deepcopy(self.metagraph.hotkeys)

    def update_scores(self, rewards: torch.FloatTensor, uids: List[int]):
        """Performs exponential moving average on the scores based on the rewards received from the miners."""

        # Check if rewards contains NaN values.
        if torch.isnan(rewards).any():
            bt.logging.warning(f"NaN values detected in rewards: {rewards}")
            # Replace any NaN values in rewards with 0.
            rewards = torch.nan_to_num(rewards, 0)

        # Check if `uids` is already a tensor and clone it to avoid the warning.
        if isinstance(uids, torch.Tensor):
            uids_tensor = uids.clone().detach()
        else:
            uids_tensor = torch.tensor(uids).to(self.device)

        # Compute forward pass rewards, assumes uids are mutually exclusive.
        # shape: [ metagraph.n ]
        self.scores = torch.zeros_like(self.scores)
        self.scores: torch.FloatTensor = self.scores.scatter(
            0, uids_tensor, rewards
        ).to(self.device)
        bt.logging.debug(f"Scattered rewards: {self.scores}")
        
        # # Update scores with rewards produced by this step.
        # # shape: [ metagraph.n ]
        # alpha: float = self.config.neuron.moving_average_alpha
        # self.scores: torch.FloatTensor = alpha * scattered_rewards + (
        #     1 - alpha
        # ) * self.scores.to(self.device)
        # bt.logging.debug(f"Updated moving avg scores: {self.scores}")

    def save_state(self):
        """Saves the state of the validator to a file."""
        bt.logging.info("Saving validator state.")
        # Save the state of the validator to file.
        torch.save(
            {
                "step": self.step,
                "scores": self.scores,
                "hotkeys": self.hotkeys,
                "scores": self.scores,
            },
            self.config.neuron.full_path + "/state.pt",
        )

    def load_state(self):
        try:
            bt.logging.info("Loading validator state.")

            # Attempt to load the state of the validator from file
            state_path = self.config.neuron.full_path + "/state.pt"
            state = torch.load(state_path)

            # Update the validator's attributes with the loaded state
            self.step = state.get("step")
            self.scores = state.get("scores")
            self.hotkeys = state.get("hotkeys")
            print(self.scores)

        except FileNotFoundError:
            bt.logging.warning(f"State file not found at {state_path}. State does not exist, perhaps running validator for the first time.")
        except Exception as e:
            bt.logging.error(f"An error occurred while loading the state: {e}")
        
