#!/bin/bash
set -euo pipefail

sudo cp pseudo-dwt.py /usr/local/bin/pseudo-dwt.py
sudo chmod +x /usr/local/bin/pseudo-dwt.py
sudo cp pseudo-dwt.service /etc/systemd/system/pseudo-dwt.service
sudo systemctl daemon-reload
sudo systemctl enable --now pseudo-dwt.service
