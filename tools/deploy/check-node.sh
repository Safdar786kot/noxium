#!/usr/bin/env bash
# Quick health check for a Noxium node. Usage: check-node.sh [rpc-host:port]  (default 127.0.0.1:17751)
T=${1:-127.0.0.1:17751}
curl -fsS "http://$T/get_info" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("height      ", d["height"], "/", d["target_height"] or d["height"])
print("synced      ", d["synchronized"])
print("peers       ", d["outgoing_connections_count"], "out,", d["incoming_connections_count"], "in")
print("difficulty  ", d["difficulty"])
print("top block   ", d["top_block_hash"])
print("network     ", d["nettype"], "version", d["version"])'
