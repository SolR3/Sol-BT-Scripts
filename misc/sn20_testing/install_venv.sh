#!/bin/bash

python3 -m venv .venvsglang
# note to change cu121 in this path according to this page: https://docs.flashinfer.ai/installation.html
./.venvsglang/bin/pip install flashinfer -i https://flashinfer.ai/whl/cu121/torch2.4/ 
./.venvsglang/bin/pip install -r requirements.sglang.txt
