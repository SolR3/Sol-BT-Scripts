#!/bin/bash

PORT1=8000
PATH_TO_BROWSE1="/root/.pm2/logs/"

PUBLIC_IP=$(curl -4 icanhazip.com)

USERNAME="rizzo"
PASSWORD="logshare"

# Function to check if a port is in use and kill the process using it
function free_port {
    local pid
    pid=$(lsof -ti tcp:$1)
    if [[ -n "$pid" ]]; then
        echo "Port $1 is already in use by PID $pid. Attempting to kill the process..."
        kill -9 $pid
        echo "Port $1 is now free."
    fi
}

# Free the port if it's already in use
free_port $PORT1

# Open the port temporarily with UFW
ufw allow $PORT1/tcp comment 'temporary--close this port if you see it later but it should autoremove'

# Start HTTP servers with basic authentication on the specified ports
python3 auth_http_server.py $PORT1 "$PATH_TO_BROWSE1" "$USERNAME" "$PASSWORD" &
PYTHON_PID=$!

# Trap to close the port and terminate the Python process when stopping the script
trap 'kill -9 $PYTHON_PID 2>/dev/null; ufw delete allow $PORT1/tcp; exit 0' SIGINT SIGTERM

# Print access instructions
echo "Server running for logs at http://$PUBLIC_IP:$PORT1 with username: $USERNAME and password: $PASSWORD"

# Keep the script running in the foreground for PM2 to manage
wait $PYTHON_PID
