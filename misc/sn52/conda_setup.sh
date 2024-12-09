#!/bin/bash

# setup conda env using miniconda, and follow the setup
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda3/miniconda.sh
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3

# verify conda installation
conda info

# create python env and install dependencies
conda create -n dojo_py311 python=3.11
conda activate dojo_py311
make install
