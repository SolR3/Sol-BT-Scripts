#!/bin/bash

sudo chmod -R +777 /root/.bittensor/subnets/finetuning/model-store

pm2 stop all
pm2 delete all

cd ~/.bittensor/subnets/finetuning

git checkout main
git fetch
git stash
git pull

python3 -m pip install -r requirements.txt
python3 -m pip install -e .

wget scriptweave.com/octo/dotenv-sn37-finetuning.env.blob -O ~/.bittensor/subnets/finetuning/.env

#sn33 api key #WARNING THIS SCRIPT DOESN'T SEEM TO BE WORKING, do manually
api_key='82cabffbc44b820e85df6bc1597567ec3d80de66'; grep -qxF "export WANDB_ACCESS_TOKEN=$api_key" ~/.bashrc || sed -i "/^export WANDB_ACCESS_TOKEN=/d" ~/.bashrc && echo "export WANDB_ACCESS_TOKEN=$api_key" >> ~/.bashrc && source ~/.bashrc
echo "exporting WANDB_ACCESS_TOKEN key, ctrl-C and do source after this if new!!!!"
sleep 3

#04
pm2 start scripts/start_validator.py \
 --time \
 --name finetune-vali-updater \
 --interpreter python3 \
 -- \
 --pm2_name finetune-vali \
 --wallet.name RizzoNetwork \
 --wallet.hotkey rizzo2 \
 --netuid 37 \
 --subtensor.chain_endpoint ws://subtensor-777.rizzo.network:9944 \
 --axon.port 16718 --logging.debug --logging.trace  

pm2 log
