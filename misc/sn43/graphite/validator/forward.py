# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# Graphite-AI
# Copyright © 2024 Graphite-AI

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

import bittensor as bt
from bittensor import axon, dendrite

from graphite.validator.reward import get_rewards, ScoreResponse
from graphite.utils.uids import get_available_uids

import time
from datetime import datetime

from graphite.protocol import GraphV2Problem, GraphV2ProblemMulti, GraphV2ProblemMultiConstrained, GraphV2Synapse, MAX_SALESMEN
        
import numpy as np
import json
import wandb
import os
import random
import requests
import math

from pydantic import ValidationError

async def forward(self):

    """
    The forward function is called by the validator every time step.

    It is responsible for querying the network and scoring the responses.

    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.

    """

    bt.logging.info(f"CONCURRENCY IDX: {self.concurrencyIdx}")
    curr_idx = self.concurrencyIdx
    self.concurrencyIdx += 1

    did_organic_task = False
    organic_task_id = ""
    try:
        if self.bearer_token_is_valid:

            url = f"{self.organic_endpoint}/tasks/oldest/{curr_idx}"
            headers = {"Authorization": "Bearer %s"%self.db_bearer_token}
            api_response = requests.get(url, headers=headers)
            api_response_output = api_response.json()
            
            organic_task_id = api_response_output["_id"]
            del api_response_output["_id"]

            did_organic_task = True

            # bt.logging.info(f"ORGANIC TRAFFIC {api_response.text}")
        else:
            api_response_output = []
    except:
        api_response_output = []

    # problem weights
    ref_tsp_value = 0.1
    ref_mtsp_value = 0.1
    ref_mdmtsp_value = 0.1 
    ref_cmdmtsp_value = 0.7

    bt.logging.info(f"Selecting mTSP with a probability of: {ref_tsp_value}")
    # randomly select n_nodes indexes from the selected graph
    prob_select = random.randint(0, len(list(self.loaded_datasets.keys()))-1)
    dataset_ref = list(self.loaded_datasets.keys())[prob_select]
    selected_problem_type_prob = random.random()
    test_problem_obj = None
    if selected_problem_type_prob < ref_tsp_value:
        n_nodes = random.randint(2000, 5000)
        bt.logging.info(f"n_nodes V2 TSP {n_nodes}")
        bt.logging.info(f"dataset ref {dataset_ref} selected from {list(self.loaded_datasets.keys())}" )
        selected_node_idxs = random.sample(range(len(self.loaded_datasets[dataset_ref]['data'])), n_nodes)
        try:
            test_problem_obj = GraphV2Problem(problem_type="Metric TSP", n_nodes=n_nodes, selected_ids=selected_node_idxs, cost_function="Geom", dataset_ref=dataset_ref)
        except ValidationError as e:
            bt.logging.debug(f"GraphV2Problem Validation Error: {e.json()}")
            bt.logging.debug(e.errors())
            bt.logging.debug(e)
    elif selected_problem_type_prob < ref_tsp_value + ref_mtsp_value:
        # single depot mTSP
        n_nodes = random.randint(500, 2000)
        bt.logging.info(f"n_nodes V2 mTSP {n_nodes}")
        bt.logging.info(f"dataset ref {dataset_ref} selected from {list(self.loaded_datasets.keys())}" )
        selected_node_idxs = random.sample(range(len(self.loaded_datasets[dataset_ref]['data'])), n_nodes)
        m = random.randint(2, 10)
        try:
            test_problem_obj = GraphV2ProblemMulti(problem_type="Metric mTSP", 
                                                    n_nodes=n_nodes, 
                                                    selected_ids=selected_node_idxs, 
                                                    cost_function="Geom", 
                                                    dataset_ref=dataset_ref, 
                                                    n_salesmen=m, 
                                                    depots=[0 for _ in range(m)])
        except ValidationError as e:
            bt.logging.debug(f"GraphV2ProblemMulti Validation Error: {e.json()}")
            bt.logging.debug(e.errors())
            bt.logging.debug(e)
    elif selected_problem_type_prob < ref_tsp_value + ref_mtsp_value + ref_mdmtsp_value:
        # multi depot mTSP
        n_nodes = random.randint(500, 2000)
        bt.logging.info(f"n_nodes V2 mTSP {n_nodes}")
        bt.logging.info(f"dataset ref {dataset_ref} selected from {list(self.loaded_datasets.keys())}" )
        selected_node_idxs = random.sample(range(len(self.loaded_datasets[dataset_ref]['data'])), n_nodes)
        m = random.randint(2, 10)
        try:
            test_problem_obj = GraphV2ProblemMulti(problem_type="Metric mTSP", 
                                                    n_nodes=n_nodes, 
                                                    selected_ids=selected_node_idxs, 
                                                    cost_function="Geom", 
                                                    dataset_ref=dataset_ref, 
                                                    n_salesmen=m, 
                                                    depots=sorted(random.sample(list(range(n_nodes)), k=m)), 
                                                    single_depot=False)
        except ValidationError as e:
            bt.logging.debug(f"GraphV2ProblemMulti Validation Error: {e.json()}")
            bt.logging.debug(e.errors())
            bt.logging.debug(e)
    else:
        # constrained multi depot mTSP
        n_nodes = random.randint(500, 2000)
        bt.logging.info(f"n_nodes V2 cmTSP {n_nodes}")
        bt.logging.info(f"dataset ref {dataset_ref} selected from {list(self.loaded_datasets.keys())}" )
        selected_node_idxs = random.sample(range(len(self.loaded_datasets[dataset_ref]['data'])), n_nodes)
        m = random.randint(2, 10)
        constraint = []
        depots = sorted(random.sample(list(range(n_nodes)), k=m))
        demand = [1]*n_nodes
        for depot in depots:
            demand[depot] = 0
        constraint = [(math.ceil(n_nodes/m) + random.randint(0, int(n_nodes/m * 0.3)) - random.randint(0, int(n_nodes/m * 0.2))) for _ in range(m-1)]
        constraint += [(math.ceil(n_nodes/m) + random.randint(0, int(n_nodes/m * 0.3)) - random.randint(0, int(n_nodes/m * 0.2)))] if sum(constraint) > n_nodes - (math.ceil(n_nodes/m) - random.randint(0, int(n_nodes/m * 0.2))) else [(n_nodes - sum(constraint) + random.randint(int(n_nodes/m * 0.2), int(n_nodes/m * 0.3)))]
        try:
            test_problem_obj = GraphV2ProblemMultiConstrained(problem_type="Metric cmTSP", 
                                                    n_nodes=n_nodes, 
                                                    selected_ids=selected_node_idxs, 
                                                    cost_function="Geom", 
                                                    dataset_ref=dataset_ref, 
                                                    n_salesmen=m, 
                                                    depots=depots, 
                                                    single_depot=False,
                                                    demand=demand,
                                                    constraint=constraint)
        except ValidationError as e:
            bt.logging.debug(f"GraphV2ProblemMultiConstrained Validation Error: {e.json()}")
            bt.logging.debug(e.errors())
            bt.logging.debug(e)
    
    if test_problem_obj:
        try:
            graphsynapse_req = GraphV2Synapse(problem=test_problem_obj)
            if "mTSP" in graphsynapse_req.problem.problem_type:
                bt.logging.info(f"GraphV2Synapse {graphsynapse_req.problem.problem_type}, n_nodes: {graphsynapse_req.problem.n_nodes}, depots: {graphsynapse_req.problem.depots}\n")
            else:
                bt.logging.info(f"GraphV2Synapse {graphsynapse_req.problem.problem_type}, n_nodes: {graphsynapse_req.problem.n_nodes}\n")
        except ValidationError as e:
            bt.logging.debug(f"GraphV2Synapse Validation Error: {e.json()}")
            bt.logging.debug(e.errors())
            bt.logging.debug(e)


    # prob_select = random.randint(1, 2)
    
    # available_uids = await self.get_available_uids()
    
    if len(api_response_output) > 0:
        # if this is an organic request, we select the top k miners by incentive (with a mix of some outside the top k to increase solution diversity)
        selected_uids = await self.get_top_k_uids()
    else:
        # select random 30 miners that are available (i.e. responded to the isAlive synapse)
        selected_uids = await self.get_k_uids()
    # selected_uids = await self.get_available_uids()

    miner_uids = list(selected_uids.keys())
    bt.logging.info(f"Selected UIDS: {miner_uids}")

    reconstruct_edge_start_time = time.time()
    if isinstance(test_problem_obj, GraphV2Problem):
        edges = self.recreate_edges(test_problem_obj)

    reconstruct_edge_time = time.time() - reconstruct_edge_start_time

    bt.logging.info(f"synapse type {type(graphsynapse_req)}")
    # The dendrite client queries the network.
    responses = await self.dendrite(
        axons=[self.metagraph.axons[uid] for uid in miner_uids], #miner_uids
        synapse=graphsynapse_req,
        deserialize=True,
        timeout = 30 + reconstruct_edge_time, # 30s + time to reconstruct, can scale with problem types in the future
    )

    if isinstance(test_problem_obj, GraphV2Problem):
        test_problem_obj.edges = edges
        # with open("gs_logs.txt", "a") as f:
        #     for hotkey in [self.metagraph.hotkeys[uid] for uid in miner_uids]:
        #         f.write(f"{hotkey}_{self.wallet.hotkey.ss58_address}_{edges.shape}_{time.time()}\n")

    for idx, res in enumerate(responses):
        # trace log the process times
        bt.logging.trace(f"Miner {miner_uids[idx]} status code: {res.dendrite.status_code}, process_time: {res.dendrite.process_time}")

    bt.logging.info(f"NUMBER OF RESPONSES: {len(responses)}")

    if isinstance(test_problem_obj, GraphV2Problem):
        graphsynapse_req_updated = GraphV2Synapse(problem=test_problem_obj) # reconstruct with edges
        score_response_obj = ScoreResponse(graphsynapse_req_updated)

    score_response_obj.current_num_concurrent_forwards = self.current_num_concurrent_forwards
    await score_response_obj.get_benchmark()

    rewards = get_rewards(self, score_handler=score_response_obj, responses=responses)
    rewards = rewards.numpy(force=True)

    wandb_miner_distance = [np.inf for _ in range(self.metagraph.n.item())]
    wandb_miner_solution = [[] for _ in range(self.metagraph.n.item())]
    wandb_axon_elapsed = [np.inf for _ in range(self.metagraph.n.item())]
    wandb_rewards = [0 for _ in range(self.metagraph.n.item())]
    best_solution_uid = 0
    for id, uid in enumerate(miner_uids):
        wandb_rewards[uid] = rewards[id]
        if wandb_rewards[uid] == rewards.max():
            best_solution_uid = uid
        wandb_miner_distance[uid] = score_response_obj.score_response(responses[id]) if score_response_obj.score_response(responses[id])!=None else 0
        wandb_miner_solution[uid] = responses[id].solution
        wandb_axon_elapsed[uid] = responses[id].dendrite.process_time


    # if len(responses) > 0 and did_organic_task == True:
    #     try:
    #         # url = f"{organic_endpoint}/pop_organic_task"
    #         # headers = {"Authorization": "Bearer db_bearer_token"}
    #         # api_response = requests.get(url, headers=headers)

    #         best_reward_idx = np.argmax(wandb_rewards)

    #         data = {
    #             "solution": wandb_miner_solution[best_reward_idx], 
    #             "distance": wandb_miner_distance[best_reward_idx]
    #         }
    #         url = f"{organic_endpoint}/tasks/{organic_task_id}"
    #         headers = {"Authorization": "Bearer db_bearer_token"}
    #         api_response = requests.put(url, json=data, headers=headers)

    #         did_organic_task = False
    #     except:
    #         pass

    # # clear database of old request > 10mins, both solved and unsolved
    # try:
    #     url = f"{organic_endpoint}/tasks/oldest"
    #     headers = {"Authorization": "Bearer db_bearer_token"}
    #     api_response = requests.delete(url, headers=headers)
    # except:
    #     pass

    configDict = {
                    "save_code": False,
                    "log_code": False,
                    "save_model": False,
                    "log_model": False,
                    "sync_tensorboard": False,
                }
    try:
        configDict["problem_type"] = graphsynapse_req.problem.problem_type
    except:
        pass
    try:
        configDict["objective_function"] = graphsynapse_req.problem.objective_function
    except:
        pass
    try:
        configDict["visit_all"] = graphsynapse_req.problem.visit_all
    except:
        pass
    try:
        configDict["to_origin"] = graphsynapse_req.problem.to_origin
    except:
        pass
    try:
        configDict["n_nodes"] = graphsynapse_req.problem.n_nodes
    except:
        pass
    try:
        configDict["nodes"] = graphsynapse_req.problem.nodes
    except:
        pass
    try:
        configDict["edges"] = []
    except:
        pass
    try:
        configDict["directed"] = graphsynapse_req.problem.directed
    except:
        pass
    try:
        configDict["simple"] = graphsynapse_req.problem.simple
    except:
        pass
    try:
        configDict["weighted"] = graphsynapse_req.problem.weighted
    except:
        pass
    try:
        configDict["repeating"] = graphsynapse_req.problem.repeating
    except:
        pass


    try:
        configDict["selected_ids"] = graphsynapse_req.problem.selected_ids
    except:
        pass
    try:
        configDict["cost_function"] = graphsynapse_req.problem.cost_function
    except:
        pass
    try:
        configDict["dataset_ref"] = graphsynapse_req.problem.dataset_ref
    except:
        pass
    try:
        configDict["selected_uids"] = miner_uids
    except:
        pass
    try:
        configDict["n_salesmen"] = graphsynapse_req.problem.n_salesmen
        configDict["depots"] = graphsynapse_req.problem.depots
    except:
        pass
    try:
        configDict["demand"] = graphsynapse_req.problem.demand
        configDict["constraint"] = graphsynapse_req.problem.constraint
    except:
        pass

    try:
        configDict["time_elapsed"] = wandb_axon_elapsed
    except:
        pass

    try:
        configDict["best_solution"] = wandb_miner_solution[best_solution_uid]
    except:
        pass
    
    if isinstance(test_problem_obj, GraphV2Problem):
        try:
            if self.subtensor.network == "test":
                wandb.init(
                    entity='graphite-subnet',
                    project="graphite-testnet",
                    config=configDict,
                    name=json.dumps({
                        "n_nodes": graphsynapse_req.problem.n_nodes,
                        "time": time.time(),
                        "validator": self.wallet.hotkey.ss58_address,
                        }),
                )
            else:
                wandb.init(
                    entity='graphite-ai',
                    project="Graphite-Subnet-V2",
                    config=configDict,
                    name=json.dumps({
                        "n_nodes": graphsynapse_req.problem.n_nodes,
                        "time": time.time(),
                        "validator": self.wallet.hotkey.ss58_address,
                        }),
                )
            for rewIdx in range(self.metagraph.n.item()):
                wandb.log({f"rewards-{self.wallet.hotkey.ss58_address}": wandb_rewards[rewIdx], f"distance-{self.wallet.hotkey.ss58_address}": wandb_miner_distance[rewIdx]}, step=int(rewIdx))

            self.cleanup_wandb(wandb)
        except Exception as e:
            print(f"Error initializing W&B: {e}")

    
    bt.logging.info(f"Scored responses: {rewards}")
    
    
    if len(rewards) > 0 and max(rewards) == 1:
        self.update_scores(rewards, miner_uids)
        time.sleep(16) # for each block, limit 1 request per block
    elif max(rewards) == 0.2:
        new_rewards = []
        new_miner_uids = []
        for i in range(len(rewards)):
            if rewards[i] != 0.2:
                new_rewards.append(0)
                new_miner_uids.append(miner_uids[i])
        new_rewards = np.array(new_rewards)  # Creates (N,)
        if len(new_miner_uids) > 0:
            self.update_scores(new_rewards, new_miner_uids)
            time.sleep(16) # for each block, limit 1 request per block

