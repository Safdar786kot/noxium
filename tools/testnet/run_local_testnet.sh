#!/bin/bash
# Start a 3-node Noxium testnet on this machine (localhost), with 2 mining nodes and 3 wallets.
#   usage: tools/testnet/run_local_testnet.sh [workdir]     stop: tools/testnet/stop_local_testnet.sh [workdir]
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
BIN=${BIN:-$ROOT/build/release/bin}
W=${1:-/tmp/nox-testnet}
mkdir -p "$W"
cd "$W"

# node  p2p   rpc   zmq
NODES=("a 27750 27751 27752" "b 27760 27761 27762" "c 27770 27771 27772")

for w in alice bob carol; do
  [ -f "$w.keys" ] || "$BIN/noxium-wallet-cli" --testnet --generate-new-wallet "$w" --password "" \
      --mnemonic-language English --offline --log-file "$W/$w-cli.log" --command address >/dev/null
done

for n in "${NODES[@]}"; do
  set -- $n
  peers=""
  for m in "${NODES[@]}"; do set -- $m; [ "$1" != "${n%% *}" ] && peers="$peers --add-exclusive-node 127.0.0.1:$2"; done
  set -- $n
  (set -m; "$BIN/noxiumd" --testnet --data-dir "$W/node-$1" --p2p-bind-ip 127.0.0.1 --p2p-bind-port $2 \
     --rpc-bind-port $3 --zmq-rpc-bind-port $4 --allow-local-ip $peers --no-igd --non-interactive \
     --log-level 0 --log-file "$W/node-$1.log" > "$W/node-$1.out" 2>&1 &)
done

for p in 27751 27761 27771; do until curl -s "http://127.0.0.1:$p/get_info" >/dev/null 2>&1; do sleep 1; done; done

# wallet-rpc: alice->node a, bob->node c, carol->node b
start_wallet() { (set -m; "$BIN/noxium-wallet-rpc" --testnet --wallet-file "$W/$1" --password "" \
   --daemon-address 127.0.0.1:$2 --rpc-bind-port $3 --disable-rpc-login --trusted-daemon \
   --log-file "$W/$1-rpc.log" > "$W/$1-rpc.out" 2>&1 &); }
start_wallet alice 27751 27801; start_wallet bob 27771 27802; start_wallet carol 27761 27803
for p in 27801 27802 27803; do
  until curl -s "http://127.0.0.1:$p/json_rpc" -d '{"jsonrpc":"2.0","id":0,"method":"get_height"}' | grep -q height; do sleep 1; done
done

addr() { curl -s "http://127.0.0.1:$1/json_rpc" -d '{"jsonrpc":"2.0","id":0,"method":"get_address"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['address'])"; }
A=$(addr 27801); B=$(addr 27802)
# two competing miners (1 thread each) => real orphan/reorg handling between nodes
curl -s http://127.0.0.1:27751/start_mining -d "{\"miner_address\":\"$A\",\"threads_count\":1,\"do_background_mining\":false,\"ignore_battery\":true}" >/dev/null
curl -s http://127.0.0.1:27771/start_mining -d "{\"miner_address\":\"$B\",\"threads_count\":1,\"do_background_mining\":false,\"ignore_battery\":true}" >/dev/null
echo "testnet running in $W  (alice=$A)"
