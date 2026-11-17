# Noxium (NOX) consensus and security review

Scope: `git diff bad3b85 -- src CMakeLists.txt` (the working tree of `/home/user/noxium`, Monero release-v0.18 rebranded by `tools/rebrand/rebrand.py`), plus the upstream code those changes touch. I did not modify the repo. Every test program below lives under `/tmp`.

Legend for evidence:
- **[V]** I checked this by running code (a test program linked against the built `build/release` libraries, a Python re-derivation, or a live offline testnet daemon).
- **[R]** I only reasoned it through from reading the source.

## Summary

| ID | Severity | Finding |
|----|----------|---------|
| C1 | **Critical** | Monero's "block 202612" PoW workaround is still active. At height 202,612 every block's PoW hash is a fixed constant. The chain either halts for good, or block 202,612 costs no work. |
| H1 | **High** | Launch security. Difficulty starts at 1, there are no seed nodes or DNS seeds, no checkpoints, and RandomX hashrate is easy to rent. Expect instamine and 51% attacks. |
| M1 | Medium | The "burned" genesis output can be spent by anyone. Its private key comes straight from `GENESIS_SEED`, which is committed in `rebrand.py`. |
| M2 | Medium | The block-weight penalty fades away as the subsidy approaches 0. The reward drops below 0.6 NOX after about 21 years, and post-cap it is exactly 0. Miners can then grow blocks for free. |
| M3 | Medium | Alt-chain `already_generated_coins` includes fees. After a reorg, miner notifications (ZMQ `miner_data` / P2Pool) and alt-parent templates use an inflated value. Because coinbase must be exact, blocks built from them are invalid. Upstream bug, dormant on Monero (tail emission), live again on Noxium. |
| L1 | Low | `assert(reward_lo < base_reward)` aborts any non-`NDEBUG` build once the cap is reached and a block is bigger than the median. |
| L2 | Low | Monero Tor/I2P seed nodes and the moneropulse DNS blocklist are still present. |
| L3 | Low | The message-signing domain separator and key derivation are unchanged from Monero. Seed reuse gives signatures that verify on both chains, and linkable addresses. |
| L4 | Low | OpenAlias is hard-coded to `oa1:xmr` with 95/106-char addresses. Noxium addresses are 97/98/109 chars. The simplewallet CSV export cuts integrated addresses to 106 chars. |
| L5 | Low | `--check-updates` defaults to `notify` with an empty DNS list. The download URLs still point at getmonero.org. |
| L6 | Low | Hardware wallets (Trezor/Ledger) still use Monero network rules and prefixes. |
| I* | Info | Verified-OK items, stale comments, and launch-time privacy notes. See the Info section. |

---

## C1 (Critical): PoW bypass or permanent halt at height 202,612

**Where**
- `src/cryptonote_core/cryptonote_tx_utils.cpp:721-727`, inside `get_block_longhash(...)`:

  ```cpp
  // block 202612 bug workaround
  if (height == 202612)
  {
    static const std::string longhash_202612 = "84f64766475d51837ac9efbef1926486e58563c95a19fef4aec3254f03000000";
    epee::string_tools::hex_to_pod(longhash_202612, res);
    return true;
  }
  ```

**What happens**
- This check has no network-type or genesis gate, so it applies on Noxium mainnet, testnet and stagenet. Any main-chain block at height 202,612 gets this fixed "PoW hash", whatever its content or nonce. Callers include:
  - `Blockchain::handle_block_to_main_chain`, `blockchain.cpp:4170`
  - the prepare/longhash worker, `blockchain.cpp:4808`
  - the miner, via `find_nonce_for_given_block`
- `check_hash(h, D)` passes only when \(h \cdot D < 2^{256}\). For this constant, the largest difficulty that passes is **1,297,898,660**. At a 120 s target that equals about **10.8 MH/s** of network hashrate.
- Height 202,612 arrives about 281 days after launch.

**Two outcomes**
1. **Network difficulty above 1,297,898,660 (hashrate above about 10.8 MH/s; a few hundred modern desktop CPUs).** Every block at height 202,612 fails PoW on every node.
   - Miners loop forever: the hash never changes, so no nonce works.
   - Nodes reject and ban (`m_bad_pow`) peers that relay such blocks.
   - Alt blocks at that height are checked with real RandomX (`get_altblock_longhash`, `blockchain.cpp:1960`), so they can be accepted as alt blocks. But `switch_to_alternative_blockchain` re-runs `handle_block_to_main_chain`, which uses the fixed hash again, so the reorg fails.
   - Result: **the chain halts permanently** until a hard fork.
2. **Difficulty at or below that value.** Block 202,612 needs zero work. Anyone can instantly mint an unlimited number of distinct valid blocks at that height: free block reward, a race and spam vector, and a bypass of PoW at one height.

**Verified [V]**: `/tmp/h/t202612.cpp`, linked against `build/release` libs.

```
blob1 pow=84f64766...03000000
blob2 pow=84f64766...03000000            <- identical for two different blobs
check_hash(D=1297898660)=1  check_hash(D=1297898661)=0
```

**Fix** (do it before launch). Remove the special case. Keep it only if you want bit-for-bit Monero compatibility, which Noxium does not need:

```diff
--- a/src/cryptonote_core/cryptonote_tx_utils.cpp
+++ b/src/cryptonote_core/cryptonote_tx_utils.cpp
@@ bool get_block_longhash(const Blockchain *pbc, const blobdata& bd, crypto::hash& res, const uint64_t height, const int major_version, const crypto::hash *seed_hash, const int miners)
   {
-    // block 202612 bug workaround
-    if (height == 202612)
-    {
-      static const std::string longhash_202612 = "84f64766475d51837ac9efbef1926486e58563c95a19fef4aec3254f03000000";
-      epee::string_tools::hex_to_pod(longhash_202612, res);
-      return true;
-    }
     if (major_version >= RX_BLOCK_VERSION)
```

Also remove these, for hygiene:
- The block-id exception in `src/cryptonote_basic/cryptonote_format_utils.cpp:1494-1517` (`calculate_block_hash`). It only triggers for one specific Monero blob hash, so it is effectively dead code [R].
- `blockchain_db.cpp:455+`. It is gated on Monero's genesis hash and is inert [R].

Add a unit test that the PoW hash at height 202,612 depends on the blob. A good sweep for leftovers: `rg -n "202612|1009827|1220516" src`.

---

## H1 (High): Launch-time security (instamine, 51%, eclipse)

**Facts** [V] from a live offline testnet daemon: `noxiumd --testnet --offline`, mining over RPC.
- Difficulties for heights 1–4 were 1, 1, 120, 338. The first blocks are essentially free.
- Block 1 is v1, which means CryptoNight-v0 PoW and a 60 s target.

**Configuration gaps**
- No seed nodes or DNS seeds: `rebrand.py` `SEED_NODES`/`DNS_SEEDS` are empty, as are `net_node.inl` `get_ip_seed_nodes` and `net_node.h` `m_seed_nodes_list`.
- No checkpoints and no DNS checkpoints (`checkpoints.cpp`).
- No precomputed block hashes (`blocks.cpp` returns `nullptr`).

**Why this is a problem**
- RandomX hashrate is a large rentable market; Monero runs at several GH/s. Renting a fraction of a percent of Monero's hashrate gives majority control of a new chain. That allows deep reorgs, double spends against exchanges, and dominating early emission.
- Difficulty uses Monero's 720-block window with a 60-block timestamp cut. Miners can push timestamps up to 2 h into the future (`CRYPTONOTE_BLOCK_FUTURE_TIME_LIMIT`), which skews the early windows [R].
- With no seeds, every node bootstraps from manual `--add-peer`/`--add-priority-node` input. That makes eclipse attacks and partitions easy.

**Recommendations**
1. Fill in `SEED_NODES`/`DNS_SEEDS` (several independent operators and ASNs) before release.
2. Add checkpoints regularly after launch (`CHECKPOINTS` in `rebrand.py`). Consider a DNSSEC-signed DNS checkpoint domain under your control; the code path exists and the URL list is empty.
3. Announce the launch time publicly and start with a reasonable miner set, so the first ~720 blocks aren't dominated by one party.
4. Optional consensus hardening before launch:
   - A minimum difficulty floor for the first N blocks.
   - Making block 1 v16 too (`{1,1}` → `{16,1}`, as in Monero's regtest table `cryptonote_core.cpp:672`), so no CryptoNight-v0 block exists.
5. Tell exchanges to require many confirmations early on.

---

## M1 (Medium): The genesis reward is not burned; anyone can spend it

**Where**
- `tools/rebrand/rebrand.py:47` (`GENESIS_SEED` is committed) and `:90-91, :103`:

  ```python
  s = sha512(GENESIS_SEED + "|out|" + net) mod l
  out_key = s*B
  ```

The comment "secret scalar is never stored -> burned" is wrong: the scalar is recomputed by anyone who reads the repo.

**Verified [V]**: I re-derived the scalar and cross-checked it with libsodium (`crypto_scalarmult_ed25519_base_noclamp`). It matches the output key in `GENESIS_TX` for all three nets. The mainnet one-time private key is `79ffa312ae434ebe083ec0edeca06ea50a59e51837105e326aa4f916317ab60b`.

**Why it can be spent**
- The genesis output has a unique pre-RCT amount: 4,291,534,423,828, i.e. 4.2915 NOX.
- Under v16 rules it is "unmixable": `n_outputs <= min_mixin` at `blockchain.cpp:3286-3291`.
- The code still accepts a ring of size 1 when an input is unmixable (`blockchain.cpp:3318-3331`). It also allows a v1 transaction for it (`min_tx_version`, `blockchain.cpp:3351`).
- So anyone can sweep it once it unlocks [R for the full spend path; the key derivation is V].

**Impact**: about 4.29 NOX (0.000024% of supply), and a false claim in the docs. It also hands a "first mover" prize to whoever reads the repo.

**Fix**: regenerate the genesis output key as a nothing-up-my-sleeve point with unknown discrete log. Do not use a scalar times B. For example: hash a public string with a counter to a y-coordinate, decompress, reject failures and small-order points, multiply by 8, and publish the procedure. Do this before launch; it changes the genesis hash.

```python
def _nums_point(tag):
    ctr = 0
    while True:
        y = int.from_bytes(hashlib.sha512(f"{tag}|{ctr}".encode()).digest()[:32], "little") & ((1 << 255) - 1)
        P = _decompress(y)            # return None if not on curve
        if P is not None:
            P8 = _mul(8, P)
            if not _is_identity(P8):
                return _enc(P8)
        ctr += 1
out_key = _nums_point("Noxium genesis burn " + net)
```

Also, if you want the cap to mean "spendable supply", either document that MONEY_SUPPLY includes the burned genesis amount or remove it.

---

## M2 (Medium, long-term consensus economics): The block-size penalty disappears with the subsidy

**Where**: `cryptonote_basic_impl.cpp:84-130`. Only `base_reward` is penalised; fees never are.

**Background**: Monero's dynamic block size relies on the quadratic penalty on the subsidy to deter bloat. Tail emission (0.6 XMR) keeps that deterrent alive. Noxium has no tail emission.

**Numbers** [V] (my re-implementation of the function, plus the library `get_block_reward`):
- The reward falls below 0.6 NOX at block 5,579,719, about 21.2 years.
- It falls below 0.001 NOX at block about 18,995,049, about 72 years.
- After the cap it is exactly 0, so `fill_block_template` (`tx_pool.cpp:1572-1635`) loses nothing by filling blocks up to `2*median`.

**Effect**
- A miner can stuff blocks with its own transactions (the fees go back to itself) and push the medians up as fast as the long-term-median clamps allow. That means faster chain growth and higher node costs, at no cost to the miner.
- `FEE_REFERENCE_MIN_REWARD` keeps the minimum relay fee sensible, but it does not restore a cost for producing big blocks.

**Options** (decide before launch, since all of them are consensus changes):
- (a) Penalise against a reference reward: \(P = \text{ref}\cdot\big((W/M)-1\big)^2\) with \(\text{ref} = \max(\text{base\_reward}, \text{FEE\_REFERENCE\_MIN\_REWARD})\). Deduct whatever exceeds the subsidy from fees, so the miner gets \(\text{base}+\text{fees}-P\) (invalid if negative). This must be mirrored in `validate_miner_transaction`, `construct_miner_tx`, `fill_block_template` and any external pool software.
- (b) Accept and document "fees-only" security, and keep watching block growth.
- (c) A tiny tail emission. This contradicts the hard-cap goal.

---

## M3 (Medium): Alt-chain `already_generated_coins` includes fees

**Where**
- `src/cryptonote_core/blockchain.cpp:1915-1917` (`handle_alternative_block`):

  ```cpp
  uint64_t block_reward = get_outs_money_amount(b.miner_tx);   // subsidy + fees
  bei.already_generated_coins = ... prev_generated_coins + block_reward ...
  ```

- The main chain does it correctly, adding `money_in_use - fee` (`blockchain.cpp:1389` and `:4449`).

**Who uses the wrong value**
- `switch_to_alternative_blockchain` → `send_miner_notifications(..., alt_chain.back().already_generated_coins)` (`blockchain.cpp:1204`). After every reorg, ZMQ `miner_data` subscribers (P2Pool) get an inflated value.
- `create_block_template` with an alt parent (`blockchain.cpp:1587`).

**Why it bites on Noxium**: pre-cap, the reward is `(MONEY_SUPPLY - agc) >> 21`, so a fee-inflated `agc` produces a slightly smaller reward. `HF_VERSION_EXACT_COINBASE` (active from height 2) then rejects the block (`blockchain.cpp:1373-1380`). Pools waste work after reorgs [R].

Monero has the same code, but in tail emission the subsidy no longer depends on `agc`, so the bug is dormant there.

**Fix (minimal)**

```diff
@@ Blockchain::switch_to_alternative_blockchain
-    send_miner_notifications(new_height, seedhash, prev_id, alt_chain.back().already_generated_coins);
+    send_miner_notifications(new_height, seedhash, prev_id, m_db->get_block_already_generated_coins(new_height - 1));
```

For alt-parent templates, do one of these: compute `agc = prev_agc + outs - fees` by loading the alt block's transactions; or refuse alt-parent templates (`return false`) until that is implemented. Ideally store the correct value in `bei` by summing the fees of the alt block's transactions when they are available.

---

## L1 (Low): The debug-build assert aborts post-cap

**Where**: `cryptonote_basic_impl.cpp:126`, `assert(reward_lo < base_reward);`. When `base_reward == 0` (post-cap) and `median < weight <= 2*median`, `reward_lo == 0` and the assert fails.

**Verified [V]**: my copy of the function built without `-DNDEBUG` aborted with exit code 134 (`Assertion 'rlo < base_reward' failed`). The release library (`-DNDEBUG`, `CMakeLists.txt:381-382`) returns `ok=1 r=0`, which is consistent. Debug nodes and miners therefore crash post-cap, both in `fill_block_template` and in block validation.

Small `base_reward > 0` (dust) is fine: `reward_lo` floors to a value below `base_reward` [V: remaining=1 gives 0].

**Fix** (keep the `> 2*median` rejection ahead of it):

```diff
     if(current_block_weight > 2 * median_weight) {
       MERROR("Block cumulative weight is too big: " ...);
       return false;
     }
+
+    if (base_reward == 0) { // post-cap: nothing to penalise
+      reward = 0;
+      return true;
+    }
```

## L2 (Low): Monero network artifacts still present

- `src/p2p/net_node.inl:861-883`: Monero Tor (`*.onion:18083`) and I2P seed nodes are used for `--tx-proxy`/anonymous zones on MAINNET. The handshake fails on `NETWORK_ID`, so there is no cross-chain acceptance. But Noxium's anonymity zones never bootstrap, and Noxium nodes reveal themselves to Monero operators. Replace them with Noxium hidden services, or use empty sets.
- `src/p2p/net_node.inl:2131-2137`: the `blocklist.moneropulse.*` DNS blocklist. It is opt-in (`--enable-dns-blocklist` defaults to false, `net_node.cpp:162`), but when enabled Monero maintainers decide which IPs Noxium bans. Empty the list or point it at your own domain.
- Cosmetic: `net_node.h` renamed the cited paper title to "Exploring the Noxium Peer-to-Peer Network". `blockchain.cpp:4746` still says MoneroPulse.

## L3 (Low): Cross-chain signature validity and linkability with reused seeds

`cryptonote_config.h:260` `HASH_KEY_MESSAGE_SIGNING = "MoneroMessageSignature"`, and key derivation is unchanged. A user who restores a Monero seed in Noxium gets:
- The same spend and view keys. I checked [V] that an address body is identical across Noxium nets and decodes to the same keys as on Monero, so the addresses are linkable.
- `sign`/`verify` message signatures that are valid on both chains.

Change `HASH_KEY_MESSAGE_SIGNING` (e.g. `"NoxiumMessageSignature"`), and warn users in wallet UX not to reuse Monero seeds. Transaction replay is impossible (see I6).

## L4 (Low): OpenAlias and address-length assumptions

- `src/common/dns_utils.cpp:421-441` requires the `oa1:xmr` tag and exact lengths of 95 or 106 characters.
- Noxium addresses are **97** (standard), **98** (subaddress) and **109** (integrated) characters [V], so OpenAlias resolution never returns a Noxium address. It fails closed, so this is not a theft vector.
- Fix: change the tag to `oa1:nox` and validate by parsing instead of by length.
- `simplewallet.cpp:9071/9076` CSV export uses `%106.106s`, which cuts 109-char integrated addresses. Use `%s`.

## L5 (Low): Update checks

- `cryptonote_core.cpp:172-175`: `--check-updates` defaults to `notify`. `updates.cpp` now has an empty DNS list, so the check just fails.
- `updates.cpp:97` still builds `downloads.getmonero.org`/`updates.getmonero.org` URLs. With no DNS records it never downloads, but a future edit that adds records would fetch Monero binaries.
- Fix: default to `disabled` and remove or replace the URLs.

## L6 (Low): Hardware wallets

`src/device_trezor/*` and the Ledger device code speak Monero's protocol. Devices derive and display addresses with Monero network prefixes, so users could confirm the wrong address on the device. Disable HW wallet support (`-DUSE_DEVICE_TREZOR=OFF`; refuse Ledger) until there is device firmware that knows Noxium.

---

## Info (checked and OK, or notes)

### I1. Capped emission arithmetic [V]
- `MONEY_SUPPLY = 18e18 < 2^64 - 1` (headroom about 4.4e17).
- `remaining` is computed without underflow and `base_reward <= remaining` always holds, so total emission cannot pass the cap.
- `tools/tests/supply_cap_test.cpp` checks the full emission to exactly MONEY_SUPPLY.
- Library check with `construct_miner_tx(agc = MONEY_SUPPLY-5, fee = 7)`: output 12. The dust is paid and the cap is reached exactly.
- The `agc` updates `base_reward < (MONEY_SUPPLY - agc) ? agc + base_reward : MONEY_SUPPLY` (`blockchain.cpp:1917, 4449`) cannot overflow because `agc <= MONEY_SUPPLY` is maintained.
- `money_in_use` overflow is caught by `check_outs_overflow` in `prevalidate_miner_transaction` (`blockchain.cpp:1321`).
- `base_reward + fee` cannot overflow, since fees are bounded by circulating supply, which is at most 18e18 [R].
- `mul128`/`div128` with tiny or zero `base_reward` are fine apart from the debug assert (L1).
- Nothing else assumes `MONEY_SUPPLY == UINT64_MAX`. The remaining uses are wallet `ignore_outputs_above` defaults (`wallet2.cpp:1233/5089/5267`, `simplewallet.cpp:3016`), which are harmless.
- `FINAL_SUBSIDY_PER_MINUTE` is unused now. `BLOCK_REWARD_OVERESTIMATE` (10 NOX) is still above the maximum reward of 8.583 NOX, so it remains a valid upper bound.

### I2. Stale comment
`blockchain.cpp:4443-4448` still describes the tail state. Behaviour is correct; update the text.

### I3. Zero-reward coinbase [V/R]
- `construct_miner_tx` (`cryptonote_tx_utils.cpp:145`) produces a v2, `RCTTypeNull` miner tx with one output of amount 0. It serializes and round-trips [V].
- Consensus: `prevalidate_miner_transaction` does not call `check_outs_valid`, which is only applied to pool transactions (`cryptonote_core.cpp:855`). `validate_miner_transaction` checks exact coinbase, here 0 == 0 [R].
- `BlockchainDB::add_transaction` stores it as an RCT output with `zeroCommit(0) = G` (`blockchain_db.cpp:234-241`) [R].
- The wallet skips it with `MERROR "Invalid output amount, skipping"` (`wallet2.cpp:2272-2276`), which is harmless log noise. It could be downgraded to a debug log for miner transactions.
- I found no consensus-split path. Zero-amount coinbase outputs were already allowed upstream [R].

### I4. Fee floor consistency [V/R]
- The floor is applied the same way in `check_fee` (`blockchain.cpp:3681`), `get_dynamic_base_fee_estimate_2021_scaling` (`:3794`) and `get_dynamic_base_fee_estimate` (`:3836`).
- `tx_pool` uses `check_fee`. Wallets get fees from the daemon's `get_fee_estimate`. There are no other `get_dynamic_base_fee` callers [R].
- Live testnet result [V]: `fees = [290000, 1200000, 4600000, 58000000]` per byte. This matches \(F_l = 8.583\text{e}12 \cdot 3000 / 300000^2 \approx 286{,}100\), rounded up to 2 significant digits.
- Pre-cap, fees are about 14× Monero's in coin terms (the reference reward is 8.58 vs 0.6). That is an economic choice, not a bug.

### I5. Hard-fork jump 1 → 16 [V/R]
- Live offline testnet: blocks 0 and 1 are `major_version` 1, blocks from 2 on are 16. Rewards: genesis 4.291534423828, block 1 4.291533400646, block 2 8.583064754930 NOX.
- `hard_fork_info` reported `earliest_height: 2, enabled: true`.
- `HardFork::get_earliest_ideal_height_for_version` (`hardfork.cpp:383-394`) returns 2 for every version from 2 to 16, so wallet `use_fork_rules(…)` sees all intermediate features as active from height 2.
- `version_1_till = 1` (`hardfork.cpp:194`) treats heights 0 and 1 as v1.
- Monero's own regtest jumps `{1,0},{16,1}` (`cryptonote_core.cpp:672`), so this path is well exercised.
- `rx_seedheight(h) = 0` for early heights, so the seed is the genesis hash.
- Difficulty uses `get_ideal_hard_fork_version` to pick the 60/120 s target (`blockchain.cpp:1286`), which is correct.
- Consequences of v16 at height 2:
  - Ring size is exactly 16, so wallets cannot build transactions until at least 16 RCT outputs have passed the 60-block coinbase lock (roughly block 76 or later).
  - Early rings are made entirely of coinbase outputs, which is weak privacy at launch.
- Non-consensus Monero-height constants (performance only): `wallet2.cpp:7466` `v2height = 1009827` makes the wallet slightly stricter on time-based unlocks. `cryptonote_core.cpp:950` `quick_height` gives a smaller sync batch size below 1,220,516.

### I6. Genesis transactions [V]
- Decoded for all three nets: version 1, unlock_time 60, one `txin_gen` at height 0, one `txout_to_key` (tag 0x02) with amount 4,291,534,423,828 = `18e18 >> 22` (correct for a v1 60 s block), and extra = `0x01` followed by a 32-byte tx public key. No trailing bytes.
- Every output key and tx public key decompresses to a valid prime-order-subgroup point (`l·P = 0`, `8·P ≠ 0`, libsodium `is_valid_point`). The pure-Python ed25519 code in `rebrand.py` matches libsodium, and the base point encodes as `5866…66`.
- The only problem is M1: the key is public.

### I7. Network separation and replay [V/R]
- New `NETWORK_ID`s, ports (17750–37752), genesis hashes, and multi-byte varint prefixes. Addresses start with `Nx`/`Ns`/`Ni`, `Tx`/`Ts`/`Ti`, `Sx`/`Ss`/`Si` [V].
- A real Monero mainnet address fails to parse on Noxium mainnet [V].
- No remaining moneroseeds or moneropulse checkpoint or update hosts in `src`. The only leftovers are the items in L2/L5. IP seed lists are empty.
- Replay: outputs, global indices and key images are chain-local and the genesis differs, so a Monero transaction cannot be valid on Noxium or the other way round [R]. The shared ringdb directory (`~/.shared-ringdb`, `wallet2.cpp:170-176`) is keyed by genesis hash (`wallet2.cpp:9012`), so nothing is shared in practice.
- The URI scheme `noxium:` is 7 characters like `monero:`, so `substr(0,7)` stays correct (`wallet2.cpp:15977`).

### I8. Checkpoints and fast sync
- `blocks.cpp` returns `nullptr` before unreachable code, which is harmless. The embedded `.dat` files are 1 byte.
- `load_compiled_in_block_hashes` handles an empty span (`blockchain.cpp:5629-5636`) [R].
- An empty DNS checkpoint list returns early (`dns_utils.cpp:502`) [R].

## Methodology and limits

**What I ran**
- A Python decoder and ed25519 check, cross-checked with PyNaCl.
- `/tmp/nr/t.cpp`: a standalone copy of `get_block_reward` with epee `int-util`, built with and without NDEBUG, plus an emission timeline.
- `/tmp/h/t202612.cpp`, `/tmp/h/tmin.cpp` and `/tmp/h/addr.cpp`, linked against `build/release` static libraries.
- An offline testnet `noxiumd` that mined blocks 1–4 over RPC (data dir `/tmp/ntd`, now stopped).

**What I did not review in depth**
- RPC servers, multisig, MMS, wallet transaction construction beyond fee sourcing, and the Trezor/Ledger code.
- The parts of upstream Monero that the fork did not touch. I assumed they are as secure as upstream v0.18.

**Not run**: core_tests or unit_tests (the machine has 2 cores and a build was in progress), and anything past height 5. In particular, C1 was shown at the function level, not on a live chain at height 202,612.

## Re-review of fixes

Scope: /tmp/security-fixes.diff and the regenerated tree at /home/user/noxium. I did not rebuild, and I did not run unit_tests or the testnet. The testnet, supply-test and unit-test results come from the maintainer.

Legend: **[V]** means I verified it by executing code or by direct inspection. **[R]** means I reasoned about it from the code but did not execute it.

| Finding | Verdict | Notes |
|---|---|---|
| C1 | Fixed | **[V]** `get_block_longhash` no longer has the 202612 branch, and `rg 202612 src` shows no consensus special case. **[R]** In `calculate_block_hash`, `return true` after the `!hash_result` early return is exactly equivalent to the old `return hash_result` for every block. The `blob`/`block_to_blob` preamble is now dead work, as it was upstream. Optional cleanup: drop it, which saves one block serialisation per call when `blob==nullptr`. The new unit test covers `get_block_longhash` but not `calculate_block_hash`. |
| H1 (consensus part) | Fixed | **[V]** The tables are `{1,0},{16,1}` with `version_1_till=0` on all three nets. This is the same shape as Monero's regtest table. `HardFork::add_fork` accepts it (strictly increasing version, height and time), and `init()` does not add a placeholder because heights is non-empty. **[V]** The genesis block is still v1, and its reward is `MONEY_SUPPLY>>22`. The supply test was updated for the block-1 v16 reward (8.583066801293 NOX). |
| H1 (operational part) | Open | Seed nodes, DNS seeds and checkpoints are now config lists, but they are empty. The mitigations for instamine, eclipse and early 51% attacks still have to be done before launch. |
| M1 | Fixed | **[V]** `genesis_tx_hex(net)` in rebrand.py reproduces `GENESIS_TX` for mainnet, testnet and stagenet byte for byte. Each tx decodes as v1, unlock 60, amount 4291534423828, with tag 0x01 extra. The output key and the tx pubkey pass libsodium `crypto_core_ed25519_is_valid_point` (canonical, not small-order, in the prime-order subgroup). `_pub_from_seed` is gone. **[R]** `_decompress` rejects y ≥ q and non-squares. Forcing even x is fine for NUMS. Multiplying by the cofactor 8 and rejecting the identity gives a prime-order point. The l·P check is redundant but harmless. The discrete log is unknown because y comes from SHA-512 of a public string, so the output is unspendable. |
| M2 | Open (documented decision) | Not implemented. The earlier analysis still applies. |
| M3 | Fixed for the common case; small residual | **[R]** `min(outs, full_subsidy(median 0))` is exact for any block at or under the median, with or without fees. For a block that is penalised (over the median) and also has fees, agc is overestimated by `min(fees, penalty)`. The alt chain's agc is only used for alt-parent block templates and is not consensus-checked. After a reorg the main-chain agc is recomputed from the DB, and `switch_to_alternative_blockchain` now notifies from `m_db`. Worst case: a rare template that is a few atomic units off, which gets rejected. This is now Info. |
| L1 | Fixed | **[R]** `base_reward==0` returns early after the >2·median check, so it can no longer reach the assert. |
| L2 | Fixed | **[V]** The Tor, I2P and DNS blocklist lists come from config and are empty. **[R]** An empty blocklist only means nothing is blocked. |
| L3 | Fixed | **[V]** `"NoxiumMessageSignature"`. |
| L4 | Fixed | **[V]** `oa1:nox`, the length window is 90–120, and the CSV uses `%s`. **[R]** The caller still fully parses the address and checks its nettype. |
| L5 | Fixed | **[V]** The update check defaults to disabled, and the URLs use `.invalid`. |
| L6 | Fixed | **[V]** Trezor defaults to OFF, and Ledger registration was removed. **[R]** Asking for a Ledger now fails with "device not found", which is acceptable. |
| wallet2 `check_block_hard_fork_version` | Correct | **[V]/[R]** With the table {1,0},{16,1}, v1 maps to [0,1) and v16 maps to [1,∞). Versions above 16 are flagged as "wallet outdated". Versions that are missing (2–15, or 0) set `daemon_is_outdated`, so the wallet refuses such blocks. Consensus never produces them, so this is the right behaviour. Both flags are read only by the single caller (`pull_and_parse_next_blocks`). |

**Newly broken:** I found nothing. Minor notes: `calculate_block_hash` has a dead `blob` preamble; the C1 unit test does not exercise the block-id path; H1 still needs seeds and checkpoints filled in before launch.
