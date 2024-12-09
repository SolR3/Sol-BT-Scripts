#!/bin/bash

cd ~/.bittensor/subnets/dojo
echo $PWD

# Couldn't get conda installed for some reason
# Using venv in the meantime
echo "Make sure you're in the venv-sn52-dojo env"
echo "NOTE: Not sure this is necessary when running docker directly"
echo "TODO: Turn this into a conda env"
sleep 5

docker compose --env-file .env.validator -f docker-compose.validator.yaml down
docker compose --env-file .env.validator -f docker-compose.validator.yaml up --build -d validator
