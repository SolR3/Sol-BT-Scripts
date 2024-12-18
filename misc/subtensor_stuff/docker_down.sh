#!/bin/bash

# Stop any currently running Docker containers and clean up the Docker environment
docker compose down --volumes && docker system prune -a --volumes -f
