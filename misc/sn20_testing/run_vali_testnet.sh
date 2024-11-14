#!/bin/bash

pm2 start \
neurons/validator.py \
--interpreter python3 \
-- \
--netuid 76 \
--subtensor.network test \
--wallet.name bh-wsl-coldkey \
--wallet.hotkey bh-wsl-hotkey \
--wallet.path ~/.bittensor/wallets \
--axon.port 10103 \

#--run_local
