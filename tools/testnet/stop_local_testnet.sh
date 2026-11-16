#!/bin/bash
# Stop the local testnet started by run_local_testnet.sh
for p in 27801 27802 27803; do curl -s "http://127.0.0.1:$p/json_rpc" -d '{"jsonrpc":"2.0","id":0,"method":"stop_wallet"}' >/dev/null 2>&1; done
for p in 27751 27761 27771; do curl -s "http://127.0.0.1:$p/stop_daemon" >/dev/null 2>&1; done
echo stopped
