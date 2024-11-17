#!/bin/bash

pm2 start run.sh \
--name bitagent_validators_autoupdate \
-- \
--wallet.path ~/.bittensor/wallets \
--wallet.name bh-wsl-coldkey \
--wallet.hotkey bh-wsl-hotkey \
--subtensor.network test \
--netuid 76
