#!/bin/bash

# #############################################
# Courtesy of Gregbeard (Thank you Gregbeard!)
# #############################################

PORT=33393
SERVE_PATH=$1

PUBLIC_IP=$(curl -4 icanhazip.com)

USERNAME="rizzo"
PASSWORD="TaR3a5hJa6Kt0R5"

# Open the port temporarily with UFW
sudo ufw allow $PORT/tcp comment 'for serving folder conaining files to be transfered'

# Start HTTP servers with basic authentication on the specified ports
$(dirname "$0")/http_server $PORT "$SERVE_PATH" "$USERNAME" "$PASSWORD" &
HTTP_SERVER_PID=$!

# Trap to close the port and terminate the http_server process when stopping the script
trap 'kill -9 $HTTP_SERVER_PID 2>/dev/null; sudo ufw delete allow $PORT/tcp; exit 0' SIGINT SIGTERM

# Print access instructions
echo "Server running for $SERVE_PATH at http://$PUBLIC_IP:$PORT"

# Keep the script running in the foreground for PM2 to manage
wait $HTTP_SERVER_PID
