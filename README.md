<p align="center"><img src="assets/logo/noxium-logo-256.png" width="160" alt="Noxium logo"></p>

# Noxium (NOX)

Noxium is a private, limited-supply cryptocurrency forked from [Monero](https://github.com/monero-project/monero) (release-v0.18).
It keeps everything that makes Monero private — ring signatures (CLSAG, ring size 16), stealth addresses, RingCT with Bulletproofs+, view tags and RandomX CPU mining — but replaces Monero's perpetual tail emission with a **hard cap of 18,000,000 NOX**.

| | Monero | **Noxium** |
|---|---|---|
| Ticker | XMR | **NOX** |
| Max supply | unlimited (0.6 XMR/block tail emission) | **18,000,000 NOX (hard cap)** |
| Emission speed factor | 20 | **22** (smoother, Bitcoin-like curve) |
| Initial block reward | ~17.6 XMR | **~8.58 NOX** |
| Block time | 2 min | 2 min |
| Decimals | 12 | 12 (1 NOX = 10¹² piconox) |
| PoW | RandomX | RandomX (from block 2) |
| Address prefix | `4…` / `8…` | **`Nx…`** standard, **`Ni…`** integrated, **`Ns…`** subaddress |
| Testnet / stagenet addresses | `9…` / `5…` | `Tx…` / `Sx…` |
| P2P / RPC / ZMQ ports | 18080 / 18081 / 18082 | **17750 / 17751 / 17752** |
| Testnet ports | 28080-28082 | 27750-27752 |
| Stagenet ports | 38080-38082 | 37750-37752 |
| Data directory | `~/.bitmonero` | `~/.noxium` |
| Binaries | `monerod`, `monero-wallet-cli`, … | `noxiumd`, `noxium-wallet-cli`, `noxium-wallet-rpc`, … |
| Units | monero, millinero, … piconero | noxium, millinox, micronox, nanonox, piconox |
| URI scheme | `monero:` | `noxium:` |

## Emission schedule

The block reward is `(MONEY_SUPPLY − already_generated) >> 21` (for 2-minute blocks), so it decays smoothly and
**the total can never exceed 18,000,000 NOX**. There is no tail emission: when the cap is reached the reward is 0 and miners are paid by fees only.

| Milestone | Height | Time after launch |
|---|---|---|
| 50 % mined | 1,453,636 | ~5.5 years |
| 90 % mined | 4,828,871 | ~18.4 years |
| 99 % mined | 9,657,741 | ~36.7 years |
| 99.9 % mined | 14,486,611 | ~55 years |
| 100 % (last piconox) | 63,665,387 | ~242 years |

Reproduce with `python3 tools/rebrand/emission.py 18000000 22`.

Other supply-related consensus details:

* **No premine.** The genesis output (~4.29 NOX) is sent to a key whose private key was never generated (derived from a public seed string and thrown away), so it is unspendable.
* **Fee floor.** Monero derives the dynamic fee from the block reward. Once rewards shrink, Noxium uses `max(reward, 0.6 NOX)` as the fee reference so fees stay meaningful and spam stays expensive after emission ends.
* **Post-cap blocks.** A coinbase with zero reward and zero fees still gets one zero-value output, so empty blocks stay valid after the cap.

## What was changed from Monero

All changes are made by one reproducible script, [`tools/rebrand/rebrand.py`](tools/rebrand/rebrand.py). Run on a clean Monero v0.18 tree, it produces this repository. See `git log`: the first commit is untouched upstream Monero and the second commit is the rebrand.

* `src/cryptonote_config.h`: supply cap, emission factor, no tail emission, fee floor, coin name, address prefixes, ports, network IDs, new genesis transactions
* `src/cryptonote_basic/cryptonote_basic_impl.cpp`: capped `get_block_reward()`
* `src/cryptonote_core/cryptonote_tx_utils.cpp`: zero-reward coinbase support
* `src/cryptonote_core/blockchain.cpp`: fee floor
* `src/hardforks/hardforks.cpp`: new chain where block 1 is v1 and all v16 features are active from block 2
* `src/checkpoints`, `src/blocks`, `src/p2p`, `src/common/updates.cpp`: removed Monero checkpoints, seed nodes, DNS checkpoints and update checks
* user-facing names, units, URI scheme and binary names
* `assets/logo/`: Noxium logo (SVG, PNG 32–512 px, ICO)

### Making your own variant

Edit the `CONFIG` block at the top of `tools/rebrand/rebrand.py` (name, ticker, supply, emission speed, prefixes, ports, network IDs, genesis seed), then run it on a fresh Monero checkout:

```bash
git clone --recursive -b release-v0.18 https://github.com/monero-project/monero.git mycoin
python3 noxium/tools/rebrand/rebrand.py mycoin
```

To get address prefixes that start with other letters, use `tools/rebrand/find_prefix.py`.

## Building

Ubuntu/Debian dependencies:

```bash
sudo apt install build-essential cmake pkg-config libssl-dev libzmq3-dev libunbound-dev libsodium-dev \
  libunwind-dev liblzma-dev libreadline-dev libexpat1-dev libpgm-dev libhidapi-dev libusb-1.0-0-dev \
  libprotobuf-dev protobuf-compiler libudev-dev libboost-all-dev
```

Build:

```bash
mkdir -p build/release && cd build/release
cmake -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=OFF ../..
make -j$(nproc) daemon simplewallet wallet_rpc_server
# binaries end up in build/release/bin/
```

The git submodules (RandomX, supercop, rapidjson, trezor-common) are vendored in this repository, so no `git submodule update` is needed.

## Verification

These checks were run on this tree (Ubuntu 26.04, GCC, Boost 1.90):

* `tools/tests/run_supply_cap_test.sh` runs the compiled consensus `get_block_reward()` over the full emission. Results: first v16 reward 8.583064754930 NOX, cap reached after 63,665,387 blocks, total emitted is exactly 18,000,000.000000000000 NOX, and the reward is 0 afterwards. **PASS**
* Mainnet node: new genesis loads, RandomX CPU mining works, and the block rewards are 4.2915 (blocks 0–1, v1) then 8.5831 NOX (v16).
* Regtest end-to-end test: mined 120 blocks, sent 123.456 NOX from one wallet to another with ring size 16 (fee 0.0031 NOX), and the receiver's balance confirmed. Subaddresses start with `Ns…`, integrated addresses with `Ni…`, and payment URIs use `noxium:…`.

## Launching the network

```bash
# 1. first node (the seed)
./noxiumd --data-dir ~/.noxium --p2p-bind-port 17750 --rpc-bind-port 17751

# 2. create a wallet (address starts with "Nx")
./noxium-wallet-cli --generate-new-wallet ~/nox-wallets/main

# 3. mine with RandomX
#    inside noxiumd:  start_mining <your Nx… address> 2

# 4. other nodes join by pointing at the seed
./noxiumd --add-priority-node <seed-ip>:17750
```

Before a public launch, you should:

1. **Change `NETWORK_ID` and `GENESIS_SEED`** in `rebrand.py` to your own random values so your chain is unique.
2. Add your seed nodes to `get_ip_seed_nodes()` in `src/p2p/net_node.inl` (and DNS seeds in `src/p2p/net_node.h`).
3. After the chain has some history, add checkpoints in `src/checkpoints/checkpoints.cpp`.
4. Run 2+ nodes on testnet (`--testnet`) and test transfers end-to-end.
5. Get an independent security review. Consensus code is unforgiving.

Note: Monero's unit and functional tests in `tests/` expect Monero's constants (supply, genesis, prefixes), so many of them fail without updates. Build with `-DBUILD_TESTS=OFF` or update the expected values.

## License

Noxium is distributed under the same BSD-3-Clause license as Monero (see [LICENSE](LICENSE)).
Copyright (c) 2014-2022 The Monero Project. Portions Copyright (c) 2012-2013 The Cryptonote developers.
The original Monero README is kept in [docs/UPSTREAM_MONERO_README.md](docs/UPSTREAM_MONERO_README.md).
"Monero" is a trademark of the Monero Project; Noxium is an independent project and is not affiliated with or endorsed by it.
