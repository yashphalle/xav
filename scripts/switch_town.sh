#!/bin/bash
# switch_town.sh — kill CARLA and restart on a new map
# Usage: bash scripts/switch_town.sh Town03
# Waits for CARLA to accept connections before exiting.

MAP=${1:-Town01}
echo "[switch_town] Killing CARLA..."
pkill -f CarlaUE4-Linux-Shipping 2>/dev/null
pkill -f CarlaUE4.sh 2>/dev/null
sleep 5

echo "[switch_town] Starting CARLA on $MAP..."
cd ~/carla
VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json \
  nohup ./CarlaUE4.sh -quality-level=Low +Map=$MAP \
  > /tmp/carla_$MAP.log 2>&1 &

echo "[switch_town] Waiting for CARLA to accept connections..."
for i in $(seq 1 30); do
  sleep 2
  "$HOME/miniconda3/envs/carla-xav/bin/python" -c "
import carla, sys
try:
    c = carla.Client('localhost', 2000)
    c.set_timeout(3.0)
    c.get_server_version()
    print('[switch_town] CARLA ready on $MAP')
    sys.exit(0)
except:
    sys.exit(1)
" && exit 0
  echo "[switch_town] Still waiting... ($i/30)"
done
echo "[switch_town] ERROR: CARLA did not start in 60 seconds"
exit 1
