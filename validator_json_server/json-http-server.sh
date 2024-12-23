#!/bin/bash

# #############################################
# Courtesy of Gregbeard (Thank you Gregbeard!)
# #############################################

PORT1=33392
# PATH_TO_BROWSE1=/home/rizzo/.bittensor/scripts/Sol-BT-Scripts/misc/subnet_data_test
# PATH_TO_BROWSE1=/home/bhorvat/bittensor/scripts/git_projects/Sol-BT-Scripts/misc/subnet_data_test
PATH_TO_BROWSE1=~/.validator_data

PUBLIC_IP=$(curl -4 icanhazip.com)

USERNAME="rizzo"
PASSWORD="TaR3a5hJa6Kt0R5"

# Open the port temporarily with UFW
ufw allow $PORT1/tcp comment 'for serving the json file read by the huggingface page'

# Start HTTP servers with basic authentication on the specified ports
sudo python3 ./json_http_server $PORT1 "$PATH_TO_BROWSE1" "$USERNAME" "$PASSWORD" &
PYTHON_PID=$!

# Trap to close the port and terminate the Python process when stopping the script
trap 'kill -9 $PYTHON_PID 2>/dev/null; ufw delete allow $PORT1/tcp; exit 0' SIGINT SIGTERM

# Print access instructions
echo "Server running for validator json file at http://$PUBLIC_IP:$PORT1 with username: $USERNAME and password: $PASSWORD"

# Keep the script running in the foreground for PM2 to manage
wait $PYTHON_PID
