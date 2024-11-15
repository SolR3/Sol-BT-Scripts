#!/bin/bash

# No --wallet.path
# 
# pm2 start \
# neurons/validator.py \
# --interpreter python3 \
# -- \
# --netuid 76 \
# --subtensor.chain_endpoint ws://127.0.0.1:9946 \
# --wallet.name bh-wsl-coldkey \
# --wallet.hotkey bh-wsl-hotkey \
# #--axon.port 10103

# With --wallet.path
# 
# pm2 start \
# neurons/validator.py \
# --interpreter python3 \
# -- \
# --netuid 76 \
# --subtensor.chain_endpoint ws://127.0.0.1:9946 \
# --wallet.name bh-wsl-coldkey \
# --wallet.hotkey bh-wsl-hotkey \
# --wallet.path ~/.bittensor/wallets \
# #--axon.port 10103

# Charlie's args (no --wallet.path)
# 
# pm2 start \
# neurons/validator.py \
# --interpreter python3 \
# -- \
# --netuid 76 \
# --subtensor.network test \
# --wallet.name bh-wsl-coldkey \
# --wallet.hotkey bh-wsl-hotkey \
# --logging.debug \
# --axon.port 7730 \
# --log_level trace \
# --logging.trace \
# --neuron.sample_size 50 \
# --openai-api-base http://192.168.69.59:14025/v1 \
# --neuron.visible_devices 1 \
# --neuron.device cuda:0


# Charlie's args (with --wallet.path)
#
# pm2 start \
# neurons/validator.py \
# --interpreter python3 \
# -- \
# --netuid 76 \
# --subtensor.network test \
# --wallet.name bh-wsl-coldkey \
# --wallet.hotkey bh-wsl-hotkey \
# --wallet.path ~/.bittensor/wallets \
# --logging.debug \
# --axon.port 7730 \
# --log_level trace \
# --logging.trace \
# --neuron.sample_size 50 \
# --openai-api-base http://192.168.69.59:14025/v1 \
# --neuron.visible_devices 1 \
# --neuron.device cuda:0
