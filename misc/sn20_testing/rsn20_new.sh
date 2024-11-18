#!/bin/bash

# Stop running processes
pm2 stop all
pm2 delete all

# cd to folder
cd ~/.bittensor/subnets/bitagent_subnet

# install dependencies
python3 -m pip install -e .

# install sglang venv
# python3 -m venv .venvsglang
./.venvsglang/bin/pip install flashinfer -i https://flashinfer.ai/whl/cu121/torch2.4/ 
./.venvsglang/bin/pip install -r requirements.sglang.txt

# Run validator
pm2 start run.sh \
--name bitagent_validators_autoupdate \
-- \
--wallet.path ~/.bittensor/wallets \
--wallet.name RizzoNetwork \
--wallet.hotkey rizzo2 \
--netuid 20
