#!/bin/bash

# #############################################
# Courtesy of Gregbeard (Thank you Gregbeard!)
# #############################################

# 2292 VM (Jerky) - SERVER_PORT = 33392
# Burn VM         - SERVER_PORT = 1101
#
# Examples:
#
# 2292 VM (Jerky):
# > ./json-http-server.sh 33392 /home/rizzo/.bittensor/validator_data
#
# Burn VM:
# > ./json-http-server.sh 1101 /home/rizzo/.bittensor/burn_subnets_data
#

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVER_PORT=$1
DISK_PATH=$2

PUBLIC_IP=$(curl -4 icanhazip.com)

USERNAME="rizzo"
PASSWORD="TaR3a5hJa6Kt0R5"

# Open the port temporarily with UFW
sudo ufw allow $SERVER_PORT/tcp comment 'for serving the json file read by the huggingface page'

# Start HTTP servers with basic authentication on the specified ports
python3 $SCRIPT_DIR/json_http_server $SERVER_PORT "$DISK_PATH" "$USERNAME" "$PASSWORD" &
PYTHON_PID=$!

# Trap to close the port and terminate the Python process when stopping the script
trap 'sudo kill -9 $PYTHON_PID 2>/dev/null; sudo ufw delete allow $SERVER_PORT/tcp; exit 0' SIGINT SIGTERM

# Print access instructions
echo "Server running for validator json file at http://$PUBLIC_IP:$SERVER_PORT with username: $USERNAME and password: $PASSWORD"

# Keep the script running in the foreground for PM2 to manage
wait $PYTHON_PID
