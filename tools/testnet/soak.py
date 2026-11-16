#!/usr/bin/env python3
"""Soak test for the local 3-node testnet.
Every INTERVAL seconds: checks all nodes agree on the chain, checks emission vs. the cap formula,
and (once coins are unlocked) sends random transfers alice->carol, bob->carol, carol->alice.
Usage: soak.py <minutes> [report.json]"""
import json, random, sys, time, urllib.request

NODES = {"a": 27751, "b": 27761, "c": 27771}
WALLETS = {"alice": 27801, "bob": 27802, "carol": 27803}
SUPPLY, ESF = 18_000_000 * 10**12, 22
INTERVAL = 30

def rpc(port, method, params=None, path="json_rpc"):
    body = json.dumps({"jsonrpc": "2.0", "id": 0, "method": method, "params": params or {}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/{path}", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    if "error" in d: raise RuntimeError(f"{method}: {d['error']}")
    return d.get("result", d)

def info(port): return rpc(port, None, path="get_info") if False else json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/get_info", timeout=30))

def expected_emission(height):
    gen = 0
    for h in range(height):
        rem = SUPPLY - gen
        shift = ESF if h < 1 else ESF - 1        # only genesis is v1 (60 s target)
        r = rem >> shift or rem
        gen += r
    return gen

def main():
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/nox-testnet/soak-report.json"
    end = time.time() + minutes * 60
    rep = {"checks": 0, "consensus_mismatches": 0, "transfers_ok": 0, "transfers_failed": 0, "errors": [], "samples": [], "reorgs_seen": 0}
    addr = {w: rpc(p, "get_address")["address"] for w, p in WALLETS.items()}
    last_top = {}
    while time.time() < end:
        try:
            infos = {n: info(p) for n, p in NODES.items()}
            hs = {n: i["height"] for n, i in infos.items()}
            h = min(hs.values()) - 1
            hashes = {n: rpc(p, "get_block_header_by_height", {"height": h})["block_header"]["hash"] for n, p in NODES.items()}
            ok = len(set(hashes.values())) == 1
            rep["checks"] += 1
            if not ok and max(hs.values()) - min(hs.values()) <= 1:
                rep["consensus_mismatches"] += 1
            for n, i in infos.items():
                if n in last_top and i["height"] <= last_top[n][0] and i["top_block_hash"] != last_top[n][1]:
                    rep["reorgs_seen"] += 1
                last_top[n] = (i["height"], i["top_block_hash"])
            alt = sum(i.get("alt_blocks_count", 0) for i in infos.values())
            # emission check on node a, all blocks 0..h
            cs = rpc(NODES["a"], "get_coinbase_tx_sum", {"height": 0, "count": h + 1})
            emitted = int(cs["emission_amount"]); fees = int(cs["fee_amount"])
            exp = expected_emission(h + 1)
            sample = {"t": int(time.time()), "heights": hs, "agree_at": h, "agree": ok, "alt_blocks": alt,
                      "emitted": emitted, "expected": exp, "fees": fees, "difficulty": infos["a"]["difficulty"]}
            if emitted != exp: rep["errors"].append(f"emission mismatch at {h}: {emitted} != {exp}")
            # transfers
            for src, dst in (("alice", "carol"), ("bob", "carol"), ("carol", "alice")):
                rpc(WALLETS[src], "refresh")
                bal = rpc(WALLETS[src], "get_balance")
                if bal["unlocked_balance"] > 2 * 10**12:
                    amt = random.randint(1, 10**12)
                    try:
                        rpc(WALLETS[src], "transfer", {"destinations": [{"amount": amt, "address": addr[dst]}], "ring_size": 16})
                        rep["transfers_ok"] += 1
                    except Exception as e:
                        rep["transfers_failed"] += 1; rep["errors"].append(f"{src}->{dst}: {e}")
            sample["balances"] = {w: rpc(p, "get_balance")["balance"] / 1e12 for w, p in WALLETS.items()}
            rep["samples"].append(sample)
            print(json.dumps(sample), flush=True)
        except Exception as e:
            rep["errors"].append(f"{time.strftime('%H:%M:%S')} {e}")
            print("ERR", e, flush=True)
        json.dump(rep, open(out, "w"), indent=1)
        time.sleep(INTERVAL)
    json.dump(rep, open(out, "w"), indent=1)
    print("DONE", {k: v for k, v in rep.items() if k != "samples"})

main()
