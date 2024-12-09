#!/bin/bash

pm2 start \
  auto_update.py \
  --name auto-update-validator \
  --interpreter $(which python3) \
  -- \
  --env_file .env.validator \
  --service validator
