# Deploying Noxium nodes

## Seed node on a VPS (Ubuntu 22.04/24.04 or Debian 12)

Minimum: 2 vCPU, 4 GB RAM, 100 GB SSD, a static public IP. Use 3+ servers at different providers or regions.

```bash
# on each server, as root
curl -fsSLO https://raw.githubusercontent.com/Safdar786kot/noxium/main/tools/deploy/install-node.sh
bash install-node.sh \
  --tarball https://github.com/Safdar786kot/noxium/releases/download/v0.1.0/noxium-linux-x64-v0.1.0.tar.gz \
  --peer <other-seed-ip>:17750 --peer <third-seed-ip>:17750
```

The installer:
* creates a locked-down `noxium` system user;
* installs the binaries in `/opt/noxium` and the config in `/etc/noxium/noxiumd.conf`;
* stores chain data in `/var/lib/noxium`;
* adds a `noxiumd` systemd service that restarts on failure;
* opens only SSH and P2P port 17750 in `ufw`.

Options:
* `--public-rpc` adds a restricted RPC on 17751, so wallets can use your node as a remote node.
* `--network testnet` runs on the testnet instead.
* `--prune` reduces disk use.

Check a node:

```bash
tools/deploy/check-node.sh            # local
systemctl status noxiumd
tail -f /var/log/noxium/noxiumd.log
```

## Docker

```bash
docker build -t noxium .
docker run -d --name noxiumd --restart unless-stopped -p 17750:17750 -v noxium-data:/home/noxium/.noxium noxium
```

## Making the nodes the built-in seeds

1. Put the servers' addresses into `CONFIG` in `tools/rebrand/rebrand.py`:
   * `SEED_NODES["mainnet"] = ["1.2.3.4:17750", ...]`
   * optionally `DNS_SEEDS = ["seeds.yourdomain.org"]`, a DNS name with one A record per seed.
2. Regenerate the source and rebuild: `git checkout bad3b85 -- src && python3 tools/rebrand/rebrand.py`.
3. Commit, then tag a release (`git tag v0.1.0 && git push --tags`). GitHub Actions builds Linux, Windows and macOS binaries and creates a draft release with `SHA256SUMS`.
