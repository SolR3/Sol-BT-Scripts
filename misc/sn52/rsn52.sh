#!/bin/bash

cd ~/.bittensor/subnets/dojo

# Couldn't get conda installed for some reason
# Using venv in the meantime
echo "Make sure you're in the venv-sn52-dojo env"
echo "NOTE: Not sure this is necessary when running docker directly"
echo "TODO: Turn this into a conda env"
sleep 5

# 
# This is the way the devs say to do it
# 

# down existing validator services
make validator-down
make validator-pull

git pull

# restart validator
make validator

# run dataset collection 
make extract-dataset

# 
# This is how the restarter script does it. But not the way the devs say to do it
# 
# docker compose --env-file .env.validator -f docker-compose.validator.yaml down
# docker compose --env-file .env.validator -f docker-compose.validator.yaml up --build -d validator
