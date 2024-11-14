#!/bin/bash

python3 -m pip install -r requirements.txt
python3 -m pip install -e .
python3 -m pip uninstall uvloop # b/c it causes issues with threading/loops
