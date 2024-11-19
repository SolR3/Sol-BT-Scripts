#!/bin/bash

docker run \
--rm -it \
--network=host \
-v "$(pwd)/db:/db" \
ghcr.io/amacneil/dbmate new create_users_table
