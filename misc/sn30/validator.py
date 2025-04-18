import os
import sys
import time
import copy
import traceback
import torch
import sqlite3
import bittensor as bt
from uuid import UUID
from dotenv import load_dotenv
from copy import deepcopy
from argparse import ArgumentParser
from datetime import datetime, timezone, timedelta
import asyncio
import websocket
from websocket._exceptions import WebSocketConnectionClosedException
from bettensor.protocol import GameData, Metadata
from bettensor.validator.bettensor_validator import BettensorValidator
from bettensor.validator.utils.io.sports_data import SportsData
from bettensor.validator.utils.scoring.watchdog import Watchdog
from bettensor.validator.utils.io.auto_updater import perform_update
import threading
import asyncio

# Constants for timeouts (in seconds)
UPDATE_TIMEOUT = 300  # 5 minutes
GAME_DATA_TIMEOUT = 180  # 3 minutes
METAGRAPH_TIMEOUT = 120  # 2 minutes
QUERY_TIMEOUT = 180  # 3 minutes
WEBSITE_TIMEOUT = 60  # 1 minute
SCORING_TIMEOUT = 300  # 5 minutes
WEIGHTS_TIMEOUT = 180  # 3 minutes



def time_task(task_name):
    """
    Decorator that times the execution of validator tasks and logs the duration.
    
    Args:
        task_name (str): Name of the task being timed
        
    Returns:
        decorator: Wrapped function that times execution
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                bt.logging.info(f"{task_name} completed in {duration:.2f} seconds")
                return result
            except Exception as e:
                duration = time.time() - start_time
                bt.logging.error(f"{task_name} failed after {duration:.2f} seconds with error: {str(e)}")
                raise
        return wrapper
    return decorator

def log_status(validator):
    while True:
        current_time = datetime.now(timezone.utc)
        current_block = validator.subtensor.block
        blocks_until_query_axons = max(0, validator.query_axons_interval - (current_block - validator.last_queried_block))
        blocks_until_send_data = max(0, validator.send_data_to_website_interval - (current_block - validator.last_sent_data_to_website))
        blocks_until_scoring = max(0, validator.scoring_interval - (current_block - validator.last_scoring_block))
        blocks_until_set_weights = max(0, validator.set_weights_interval - (current_block - validator.last_set_weights_block))

        status_message = (
            "\n"
            "================================ VALIDATOR STATUS ================================\n"
            f"Current time: {current_time}\n"
            f"Scoring System, Current Day: {validator.scoring_system.current_day}\n"
            f"Current block: {current_block}\n"
            f"Last updated block: {validator.last_updated_block}\n"
            f"Blocks until next query_and_process_axons: {blocks_until_query_axons}\n"
            f"Blocks until send_data_to_website: {blocks_until_send_data}\n"
            f"Blocks until scoring_run: {blocks_until_scoring}\n"
            f"Blocks until set_weights: {blocks_until_set_weights}\n"
            "================================================================================\n"
        )
        
        debug_message = (
            f"Scoring System, Current Day: {validator.scoring_system.current_day}\n"
            f"Scoring System, Current Day Tiers: {validator.scoring_system.tiers[:, validator.scoring_system.current_day]}\n"
            f"Scoring System, Current Day Tiers Length: {len(validator.scoring_system.tiers[:, validator.scoring_system.current_day])}\n"
            f"Scoring System, Current Day Scores: {validator.scoring_system.composite_scores[:, validator.scoring_system.current_day, 0]}\n"
            f"Scoring System, Amount Wagered Last 5 Days: {validator.scoring_system.amount_wagered[:, validator.scoring_system.current_day]}\n"

        )

        bt.logging.info(status_message)
        #bt.logging.debug(debug_message)
        time.sleep(30)





def run(validator: BettensorValidator):
    initialize(validator)
    watchdog = Watchdog(timeout=900)  # 15 minutes timeout


    # Create a thread for periodic status logging
    status_log_thread = threading.Thread(target=log_status, args=(validator,), daemon=True)
    status_log_thread.start()

    try:
        while True:
            current_time = datetime.now(timezone.utc)
            current_block = validator.subtensor.block
            bt.logging.info(f"Current block: {current_block}")

            # Perform update (if needed)
            bt.logging.info("Perform_update called")
            perform_update(validator)

            # Update game data
            if (current_block - validator.last_updated_block) > validator.update_game_data_interval:
                update_game_data(validator, current_time)

            # Query and process axons
            if (current_block - validator.last_queried_block) > validator.query_axons_interval:
                query_and_process_axons_with_game_data(validator)

            # Send data to website
            if (current_block - validator.last_sent_data_to_website) > validator.send_data_to_website_interval:
                threading.Thread(target=send_data_to_website_server, args=(validator,), daemon=True).start()

            # Recalculate scores
            if (current_block - validator.last_scoring_block) > validator.scoring_interval:
                scoring_run(validator, current_time)

            # Set weights
            if (current_block - validator.last_set_weights_block) > validator.set_weights_interval:
                set_weights(validator, validator.scores)

            time.sleep(12)  # Control the loop iteration rate

    except Exception as e:
        bt.logging.error(f"Error in main: {str(e)}")
        bt.logging.error(traceback.format_exc())
    except KeyboardInterrupt:
        bt.logging.info("Keyboard interrupt received. Shutting down gracefully...")

    finally:
        # Ensure the status log thread is terminated
        status_log_thread.join()

def initialize(validator):
    validator.serve_axon()
    validator.initialize_connection()

    if not validator.last_updated_block:
        bt.logging.info("Updating last updated block; will set weights this iteration")
        validator.last_updated_block = validator.subtensor.block - 301
        validator.last_queried_block = validator.subtensor.block - 11
        validator.last_sent_data_to_website = validator.subtensor.block - 16
        validator.last_scoring_block = validator.subtensor.block - 51
        validator.last_set_weights_block = validator.subtensor.block - 301
    
    # Define default intervals if they don't exist
    if not hasattr(validator, 'update_game_data_interval'):
        validator.update_game_data_interval = 10  # Default value, adjust as needed

    if not hasattr(validator, 'query_axons_interval'):
        validator.query_axons_interval = 25  # Default value, adjust as needed

    if not hasattr(validator, 'send_data_to_website_interval'):
        validator.send_data_to_website_interval = 15  # Default value, adjust as needed

    if not hasattr(validator, 'scoring_interval'):
        validator.scoring_interval = 50  # Default value, adjust as needed

    if not hasattr(validator, 'set_weights_interval'):
        validator.set_weights_interval = 300  # Default value, adjust as needed

    # Define last operation block numbers if they don't exist
    if not hasattr(validator, 'last_queried_block'):
        validator.last_queried_block = validator.subtensor.block - 10

    if not hasattr(validator, 'last_sent_data_to_website'):
        validator.last_sent_data_to_website = validator.subtensor.block - 15

    if not hasattr(validator, 'last_scoring_block'):
        validator.last_scoring_block = validator.subtensor.block - 50

    if not hasattr(validator, 'last_set_weights_block'):
        validator.last_set_weights_block = validator.subtensor.block - 300


def update_game_data(validator, current_time):
    """
    Calls SportsData to update game data in the database - Async in separate thread
    """
    bt.logging.info("--------------------------------Updating game data--------------------------------")
    
    try:
        if validator.last_api_call is None:
            validator.last_api_call = current_time - timedelta(days=15)

        all_games = validator.sports_data.fetch_and_update_game_data(
            validator.last_api_call
        )
        if all_games is None:
            bt.logging.warning(
                "Failed to fetch game data. Continuing with previous data."
            )

        bt.logging.info(f"Current time: {current_time}")
        validator.last_api_call = current_time

        bt.logging.info(f"Last api call updated to: {validator.last_api_call}")
        validator.save_state()

    except Exception as e:
        bt.logging.error(f"Error fetching game data: {e}")
        bt.logging.error(f"Traceback:\n{traceback.format_exc()}")

    validator.last_updated_block = validator.subtensor.block

@time_task("sync_metagraph")
def sync_metagraph_with_retry(validator):
    max_retries = 3
    retry_delay = 60
    for attempt in range(max_retries):
        try:
            validator.metagraph = validator.sync_metagraph()
            bt.logging.info("Metagraph synced successfully.")
            return
        except websocket.WebSocketConnectionClosedException:
            if attempt < max_retries - 1:
                bt.logging.warning(f"WebSocket connection closed. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                raise
        except Exception as e:
            bt.logging.error(f"Error syncing metagraph: {str(e)}")
            bt.logging.error(f"Traceback: {traceback.format_exc()}")
            raise
        max_retries -= 1

@time_task("filter_and_update_axons")
def filter_and_update_axons(validator):
    all_axons = validator.metagraph.axons
    bt.logging.trace(f"All axons: {all_axons}")

    if validator.scores is None:
        bt.logging.warning("Scores were None. Reinitializing...")
        validator.init_default_scores()

    if validator.scores is None:
        bt.logging.error("Failed to initialize scores. Exiting.")
        return None, None, None, None

    num_uids = len(validator.metagraph.uids.tolist())
    current_scores_len = len(validator.scores)

    if num_uids > current_scores_len:
        bt.logging.info(f"Discovered new Axons, current scores: {validator.scores}")
        validator.scores = torch.cat(
            (
                validator.scores,
                torch.zeros(
                    (num_uids - current_scores_len),
                    dtype=torch.float32,
                ),
            )
        )
        bt.logging.info(f"Updated scores, new scores: {validator.scores}")

    (
        uids_to_query,
        list_of_uids,
        blacklisted_uids,
        uids_not_to_query,
    ) = validator.get_uids_to_query(all_axons=all_axons)

    if not uids_to_query:
        bt.logging.warning(f"UIDs to query is empty: {uids_to_query}")

    return uids_to_query, list_of_uids, blacklisted_uids, uids_not_to_query

@time_task("query_and_process_axons")
def query_and_process_axons_with_game_data(validator):
    """
    Queries axons with game data and processes the responses
    """
    bt.logging.info("--------------------------------Querying and processing axons with game data--------------------------------")
    validator.last_queried_block = validator.subtensor.block
    current_time = datetime.now(timezone.utc).isoformat()
    gamedata_dict = validator.fetch_local_game_data(current_timestamp=current_time)
    if gamedata_dict is None:
        bt.logging.error("No game data found")
        return None

    synapse = GameData.create(
        db_path=validator.db_path,
        wallet=validator.wallet,
        subnet_version=validator.subnet_version,
        neuron_uid=validator.uid,
        synapse_type="game_data",
        gamedata_dict=gamedata_dict,
    )
    if synapse is None:
        bt.logging.error("Synapse is None")
        return None

    bt.logging.debug(
        f"Synapse: {synapse.metadata.synapse_id} , {synapse.metadata.timestamp}, type: {synapse.metadata.synapse_type}, origin: {synapse.metadata.neuron_uid}"
    )

    responses = []
    result = filter_and_update_axons(validator)
    if result is None:
        bt.logging.error("Failed to filter and update axons")
        return None

    uids_to_query, list_of_uids, blacklisted_uids, uids_not_to_query = result

    for i in range(0, len(uids_to_query), 20):
        responses += validator.dendrite.query(
            axons=uids_to_query[i : i + 20],
            synapse=synapse,
            timeout=validator.timeout,
            deserialize=False,
        )


    bt.logging.info("Finished querying axons..")

    if not responses:
        bt.logging.info("No responses received. Sleeping for 18 seconds.")
        time.sleep(18)

    bt.logging.info(f"Received {len(responses)} responses")

    valid_responses = []
    invalid_responses = []

    bt.logging.info("Starting response processing...")
    
    for idx, response in enumerate(responses):
        try:
            bt.logging.info(f"Processing response: {idx}")
            if response.metadata.synapse_type == "prediction":
                valid_responses.append(response)
                #bt.logging.info(f"Received valid response: {response.metadata.synapse_type}")
                #bt.logging.trace(f"Response: {response}")
            else:
                invalid_responses.append(response)
                bt.logging.warning(f"Received invalid response: {response.metadata.synapse_type}")
        except Exception as e:
            bt.logging.error(f"Error processing response: {e}")
            bt.logging.error(traceback.format_exc())
            bt.logging.warning(f"Response: {response}")
            continue
    
    bt.logging.warning(f"Received {len(invalid_responses)} invalid responses: {[response.metadata.synapse_type for response in invalid_responses]}")
    bt.logging.warning(f"Affected Miners: {[response.metadata.neuron_uid for response in invalid_responses]}")

    bt.logging.info(f"Received {len(valid_responses)} valid responses - processing...")
    if valid_responses and any(valid_responses):
        try:
            validator.process_prediction(
                processed_uids=list_of_uids, synapses=valid_responses
            )
        except Exception as e:
            bt.logging.error(f"Error processing predictions: {e}")
            bt.logging.error(traceback.format_exc())

@time_task("send_data_to_website_server")
def send_data_to_website_server(validator):
    """
    Sends data to the website server
    """
    bt.logging.info("--------------------------------Sending data to website server--------------------------------")
    validator.last_sent_data_to_website = validator.subtensor.block
    bt.logging.info(f"Last sent data to website: {validator.last_sent_data_to_website}")

    try:
        result = validator.website_handler.fetch_and_send_predictions()
        bt.logging.info(f"Result status: {result}")
        if result:
            bt.logging.info("Predictions fetched and sent successfully")
        else:
            bt.logging.warning("No new predictions were sent this round")
    except Exception as e:
        bt.logging.error(f"Error in fetch_and_send_predictions: {str(e)}")

@time_task("scoring_run")
def scoring_run(validator, current_time):
    """
    calls the scoring system to update miner scores before setting weights
    """
    bt.logging.info("--------------------------------Scoring run--------------------------------")
    validator.last_scoring_block = validator.subtensor.block
    
    try:
        # Get UIDs to query and invalid UIDs
        (
            _,
            list_of_uids,
            blacklisted_uids,
            uids_not_to_query,
        ) = validator.get_uids_to_query(validator.metagraph.axons)

        valid_uids = set(list_of_uids)
        # Combine blacklisted_uids and uids_not_to_query
        invalid_uids = set(blacklisted_uids + uids_not_to_query)
        bt.logging.info(f"Invalid UIDs: {invalid_uids}")
        validator.scores = validator.scoring_system.scoring_run(
            current_time, invalid_uids, valid_uids
        )
        bt.logging.info("Scores updated successfully")
        bt.logging.info(f"Scores: {validator.scores}")

        for uid in blacklisted_uids:
            if uid is not None:
                bt.logging.debug(
                    f"Setting score for blacklisted UID: {uid}. Old score: {validator.scores[uid]}"
                )
                validator.scores[uid] = (
                    validator.neuron_config.alpha * validator.scores[uid]
                    + (1 - validator.neuron_config.alpha) * 0.0
                )
                bt.logging.debug(
                    f"Set score for blacklisted UID: {uid}. New score: {validator.scores[uid]}"
                )

        for uid in uids_not_to_query:
            if uid is not None:
                bt.logging.trace(
                    f"Setting score for not queried UID: {uid}. Old score: {validator.scores[uid]}"
                )
                validator_alpha_type = type(validator.neuron_config.alpha)
                validator_scores_type = type(validator.scores[uid])
                bt.logging.debug(
                    f"validator_alpha_type: {validator_alpha_type}, validator_scores_type: {validator_scores_type}"
                )
                validator.scores[uid] = (
                    validator.neuron_config.alpha * validator.scores[uid]
                    + (1 - validator.neuron_config.alpha) * 0.0
                )
                bt.logging.trace(
                    f"Set score for not queried UID: {uid}. New score: {validator.scores[uid]}"
                )
        bt.logging.info(f"Scoring run completed")

    except Exception as e:
        bt.logging.error(f"Error in scoring_run: {str(e)}")
        bt.logging.error(f"Traceback: {traceback.format_exc()}")
        bt.logging.error("Gonna just go ahead and continue anyways")
        # raise



@time_task("set_weights")
def set_weights(validator, scores):
    """
    Sets the weights for the validator
    """
    bt.logging.info("--------------------------------Setting weights--------------------------------")
    
    try:
        # bt.logging.info("Attempting to update weights")
        # if validator.subtensor is None:
        #     bt.logging.warning("Subtensor is None. Attempting to reinitialize...")
        #     try:
        #         validator.initialize_connection()
        #     except Exception as e:
        #         bt.logging.error(f"Error initializing connection: {str(e)}")

        if validator.subtensor is not None:
            success = validator.set_weights(scores)
            bt.logging.info("Weight update attempt completed")
        else:
            bt.logging.error(
                "Subtensor is not initialized. Skipping weight update."
            )
            success = False
    except Exception as e:
        bt.logging.error(f"Error during weight update process: {str(e)}")
        success = False

    if success:
        bt.logging.success("Successfully updated weights")
        validator.last_set_weights_block = validator.subtensor.block  # Moved inside success block
    else:
        bt.logging.warning(
            "Failed to set weights or encountered an error, continuing with next iteration."
        )
        validator.last_set_weights_block = validator.subtensor.block - 250 #reset the block number so we don't try to set weights too early, slowing down retries
    
    try:
        validator.last_updated_block = validator.subtensor.block
        bt.logging.info(f"Updated last_updated_block to {validator.last_updated_block}")
    except Exception as e:
        bt.logging.error(f"Error updating last_updated_block: {str(e)}")

# The main function parses the configuration and runs the validator.
def main():
    parser = ArgumentParser()

    parser.add_argument(
        "--subtensor.network", type=str, help="The subtensor network to connect to"
    )
    parser.add_argument(
        "--subtensor.chain_endpoint",
        type=str,
        help="The subtensor network to connect to",
    )
    parser.add_argument("--wallet.name", type=str, help="The name of the wallet to use")
    parser.add_argument(
        "--wallet.hotkey", type=str, help="The hotkey of the wallet to use"
    )
    parser.add_argument(
        "--logging.trace", action="store_true", help="Enable trace logging"
    )
    parser.add_argument(
        "--logging.debug", action="store_true", help="Enable debug logging"
    )

    parser.add_argument(
        "--alpha", type=float, default=0.9, help="The alpha value for the validator."
    )
    parser.add_argument("--netuid", type=int, default=30, help="The chain subnet uid.")
    parser.add_argument(
        "--axon.port", type=int, help="The port this axon endpoint is serving on."
    )
    parser.add_argument(
        "--max_targets",
        type=int,
        default=256,
        help="Sets the value for the number of targets to query - set to 256 to ensure all miners are queried, it is now batched",
    )
    parser.add_argument(
        "--load_state",
        type=str,
        default="True",
        help="WARNING: Setting this value to False clears the old state.",
    )
    args = parser.parse_args()
    print("Parsed arguments:", args)
    validator = BettensorValidator(parser=parser)

    if (
        not validator.apply_config(bt_classes=[bt.subtensor, bt.logging, bt.wallet])
        or not validator.initialize_neuron()
    ):
        bt.logging.error("Unable to initialize Validator. Exiting.")
        sys.exit()

    run(validator)





if __name__ == "__main__":
    main()