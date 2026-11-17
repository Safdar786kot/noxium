# Noxium launch runbook

## 1. Infrastructure (week 0)
- [ ] Rent 3 VPSs at different providers or regions (2 vCPU, 4 GB RAM, 100 GB SSD, static IPv4).
- [ ] Optional: register a domain and create `seeds.<domain>` with one A record per seed.
- [ ] Put the IPs/domain into `SEED_NODES` / `DNS_SEEDS` in `tools/rebrand/rebrand.py`, regenerate `src` and commit.

## 2. Public testnet (weeks 1–4)
- [ ] Tag a pre-release (`v0.1.0-testnet`) and let GitHub Actions build all platforms.
- [ ] On each VPS: `install-node.sh --network testnet --tarball <release URL> --peer <other seeds>`.
- [ ] Invite testers to mine (`noxiumd --testnet --add-priority-node <seed>:27750`) and send transactions.
- [ ] Remember that transfers start working only after ~76 blocks (ring size 16 needs enough unlocked outputs).
- [ ] Watch for crashes, forks and wallet errors; fix them, and tag new testnet builds.
- [ ] Optional: ask a second, paid auditor to review the consensus changes (`git diff 42a9fb5 -- src`).

## 3. Mainnet release (launch day − 7)
- [ ] Freeze the code. Tag `v1.0.0` and publish the GitHub release with `SHA256SUMS`.
- [ ] Announce the launch date/time (UTC), the release link and the genesis block hash:
      `noxiumd --print-genesis-tx` / the hash of block 0 from `get_block_header_by_height 0`.
- [ ] Line up several independent miners and a mining pool for launch, so one party can't dominate early hashrate.

## 4. Launch day
- [ ] Start the 3 seed nodes on mainnet: `install-node.sh --tarball <v1.0.0 URL> --peer ...`.
- [ ] Start mining and confirm that every seed sees the same chain (`tools/deploy/check-node.sh <ip>:17751`).
- [ ] Tell users that sending coins becomes possible roughly 2.5–3 hours after launch.

## 5. After launch
- [ ] Every few weeks, add checkpoints (`CHECKPOINTS` in `rebrand.py`) for recent block hashes and ship them in a release.
- [ ] Run a block explorer and a pool (see the README's ecosystem section).
- [ ] Keep watching for very large blocks (security review M2).
