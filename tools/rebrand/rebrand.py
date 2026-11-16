#!/usr/bin/env python3
"""
Rebrand a pristine Monero (release-v0.18) source tree into a new coin.

What it changes
  * coin name, ticker, unit names, binary names, data directory
  * address prefixes, P2P/RPC/ZMQ ports, network IDs  (so it can never
    talk to the Monero network or accept Monero addresses)
  * a brand-new genesis transaction for mainnet/testnet/stagenet
  * HARD-CAPPED supply: tail emission removed, reward = 0 once the cap is hit
  * fee calculation keeps a floor so fees don't collapse when rewards end
  * fresh hard-fork table (RandomX + all current Monero features from block 2)
  * all Monero checkpoints, seed nodes, DNS checkpoints and update checks removed

Usage:   python3 tools/rebrand/rebrand.py [path/to/source]   (default: repo root)
Edit the CONFIG block below to choose your own name / ticker / supply.
Run it ONCE on an unmodified Monero tree (it refuses to run twice).
"""
import hashlib, os, re, sys, pathlib

# ----------------------------------------------------------------------------
# CONFIG – change these to make your own coin
# ----------------------------------------------------------------------------
CONFIG = dict(
    NAME          = "Noxium",          # display name
    NAME_LOWER    = "noxium",          # used for binaries, data dir, URI scheme
    TICKER        = "NOX",
    UNIT_PREFIX   = "nox",             # millinox, micronox, nanonox, piconox
    MAX_SUPPLY    = 18_000_000,        # whole coins; max 18,446,744 with 12 decimals
    EMISSION_SPEED_FACTOR = 22,        # Monero uses 20. 22 => ~8.58 coins/block, 50% mined in ~5.5 yrs, 99% in ~37 yrs
    FEE_FLOOR_REWARD = 600_000_000_000,  # 0.6 coin; reference reward used for fees once emission ends
    # base58 prefixes chosen so addresses start with: mainnet Nx/Ni/Ns, testnet Tx/Ti/Ts, stagenet Sx/Si/Ss
    PREFIX = dict(
        mainnet  = (0x1c83, 0x6381, 0x5a82),
        testnet  = (0x0ea1, 0x561f, 0x4d20),
        stagenet = (0x119b, 0x5919, 0x4f9a),
    ),
    PORTS = dict(mainnet=(17750, 17751, 17752), testnet=(27750, 27751, 27752), stagenet=(37750, 37751, 37752)),
    # 16-byte network IDs. Change them for your own coin (any random bytes).
    NETWORK_ID = dict(
        mainnet  = "4e4f58a1c3f2117b9d02e45a6c0b7f31",
        testnet  = "4e4f58a1c3f2117b9d02e45a6c0b7f32",
        stagenet = "4e4f58a1c3f2117b9d02e45a6c0b7f33",
    ),
    GENESIS_SEED  = "Noxium genesis | 16 Nov 2026 | limited supply privacy coin",
    LAUNCH_TIME   = 1794787200,        # 2026-11-16 00:00 UTC – timestamp used in hard-fork table
)

# ----------------------------------------------------------------------------
# tiny pure-python ed25519 (only base-point multiplication is needed)
# ----------------------------------------------------------------------------
_q = 2**255 - 19
_l = 2**252 + 27742317777372353535851937790883648493
_d = -121665 * pow(121666, _q - 2, _q) % _q
_I = pow(2, (_q - 1) // 4, _q)
def _xrecover(y):
    xx = (y*y - 1) * pow(_d*y*y + 1, _q - 2, _q)
    x = pow(xx, (_q + 3) // 8, _q)
    if (x*x - xx) % _q: x = x * _I % _q
    return _q - x if x % 2 else x
_By = 4 * pow(5, _q - 2, _q) % _q
_B = (_xrecover(_By), _By, 1, _xrecover(_By) * _By % _q)
def _add(P, Q):
    x1, y1, z1, t1 = P; x2, y2, z2, t2 = Q
    a = (y1 - x1) * (y2 - x2) % _q; b = (y1 + x1) * (y2 + x2) % _q
    c = t1 * 2 * _d * t2 % _q; dd = z1 * 2 * z2 % _q
    e, f, g, h = b - a, dd - c, dd + c, b + a
    return (e*f % _q, g*h % _q, f*g % _q, e*h % _q)
def _mul(s, P=_B):
    R = (0, 1, 1, 0)
    while s:
        if s & 1: R = _add(R, P)
        P = _add(P, P); s >>= 1
    return R
def _enc(P):
    x, y, z, _ = P; zi = pow(z, _q - 2, _q); x, y = x*zi % _q, y*zi % _q
    return (y | ((x & 1) << 255)).to_bytes(32, "little")
def _pub_from_seed(tag):
    s = int.from_bytes(hashlib.sha512((CONFIG["GENESIS_SEED"] + tag).encode()).digest(), "little") % _l
    return _enc(_mul(s))

def _varint(n):
    out = b""
    while n >= 0x80: out += bytes([(n & 0x7f) | 0x80]); n >>= 7
    return out + bytes([n])

def genesis_tx_hex(net):
    """Genesis coinbase: v1 tx, unlock 60, one output to a key derived from the
    seed whose private key is thrown away (the genesis reward is unspendable)."""
    supply = CONFIG["MAX_SUPPLY"] * 10**12
    amount = supply >> CONFIG["EMISSION_SPEED_FACTOR"]   # same formula as get_block_reward() for a v1 block
    out_key = _pub_from_seed("|out|" + net)    # secret scalar is never stored -> burned
    tx_pub  = _pub_from_seed("|txkey|" + net)
    tx = (_varint(1) + _varint(60) +           # version, unlock_time
          _varint(1) + b"\xff" + _varint(0) +  # 1 input: txin_gen(height 0)
          _varint(1) + _varint(amount) + b"\x02" + out_key +   # 1 output: txout_to_key
          _varint(33) + b"\x01" + tx_pub)      # extra: tx public key
    return tx.hex()

# ----------------------------------------------------------------------------
ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[2])
C = CONFIG

def edit(rel, fn):
    p = ROOT / rel
    old = p.read_text(encoding="utf-8", errors="surrogateescape")
    new = fn(old)
    if new == old:
        sys.exit(f"[rebrand] nothing changed in {rel} – is this a pristine Monero tree?")
    p.write_text(new, encoding="utf-8", errors="surrogateescape")
    print(f"[rebrand] patched {rel}")

def sub(pattern, repl, count=0, flags=0):
    def f(s):
        n, k = re.subn(pattern, repl, s, count=count, flags=flags)
        if k == 0: sys.exit(f"[rebrand] pattern not found: {pattern!r}")
        return n
    return f

def chain(*fs):
    def f(s):
        for g in fs: s = g(s)
        return s
    return f

def uuid_bytes(h):
    return ", ".join(f"0x{h[i:i+2].upper()}" for i in range(0, 32, 2))

# --- guard -------------------------------------------------------------------
cfg = (ROOT / "src/cryptonote_config.h").read_text()
if 'CRYPTONOTE_NAME                         "bitmonero"' not in cfg:
    sys.exit("[rebrand] src/cryptonote_config.h is already modified – run on a pristine Monero tree")

# --- 1. cryptonote_config.h --------------------------------------------------
def patch_config(s):
    supply = C["MAX_SUPPLY"] * 10**12
    assert supply < 2**64, "MAX_SUPPLY too large for 12 decimal places"
    s = sub(r"#define MONEY_SUPPLY\s+\(\(uint64_t\)\(-1\)\)",
            f"#define MONEY_SUPPLY                                    ((uint64_t){supply}ull) // HARD CAP: {C['MAX_SUPPLY']:,} {C['TICKER']}")(s)
    s = sub(r"#define EMISSION_SPEED_FACTOR_PER_MINUTE\s+\(20\)",
            f"#define EMISSION_SPEED_FACTOR_PER_MINUTE                ({C['EMISSION_SPEED_FACTOR']})")(s)
    s = sub(r"#define FINAL_SUBSIDY_PER_MINUTE\s+\(\(uint64_t\)300000000000\).*",
            "#define FINAL_SUBSIDY_PER_MINUTE                        ((uint64_t)0) // no tail emission -> limited supply\n"
            f"#define FEE_REFERENCE_MIN_REWARD                        ((uint64_t){C['FEE_FLOOR_REWARD']}ull) // fee calculation floor once emission ends")(s)
    s = sub(r'#define CRYPTONOTE_NAME\s+"bitmonero"', f'#define CRYPTONOTE_NAME                         "{C["NAME_LOWER"]}"')(s)
    # per-network blocks: order in file is mainnet, testnet, stagenet
    nets = ["mainnet", "testnet", "stagenet"]
    for i, kind in enumerate(["ADDRESS", "INTEGRATED_ADDRESS", "SUBADDRESS"]):
        pat = rf"(CRYPTONOTE_PUBLIC_{kind}_BASE58_PREFIX = )\d+;"
        it = iter(nets)
        s = re.sub(pat, lambda m: m.group(1) + f"0x{C['PREFIX'][next(it)][i]:x}; // {['standard','integrated','subaddress'][i]}", s)
    for i, kind in enumerate(["P2P", "RPC", "ZMQ_RPC"]):
        pat = rf"(\b{kind}_DEFAULT_PORT = )\d+;"
        it = iter(nets)
        s = re.sub(pat, lambda m: m.group(1) + f"{C['PORTS'][next(it)][i]};", s)
    it = iter(nets)
    s = re.sub(r"(NETWORK_ID = \{ \{\s*)[^}]*?(\s*\} \})",
               lambda m: m.group(1) + uuid_bytes(C["NETWORK_ID"][next(it)]) + m.group(2), s)
    it = iter(nets)
    s = re.sub(r'(GENESIS_TX = ")[0-9a-f]+(")', lambda m: m.group(1) + genesis_tx_hex(next(it)) + m.group(2), s)
    return s
edit("src/cryptonote_config.h", patch_config)

# --- 2. emission: hard cap ---------------------------------------------------
edit("src/cryptonote_basic/cryptonote_basic_impl.cpp", sub(
    r"    uint64_t base_reward = \(MONEY_SUPPLY - already_generated_coins\) >> emission_speed_factor;\n"
    r"    if \(base_reward < FINAL_SUBSIDY_PER_MINUTE\*target_minutes\)\n    \{\n"
    r"      base_reward = FINAL_SUBSIDY_PER_MINUTE\*target_minutes;\n    \}\n",
    "    // LIMITED SUPPLY: smooth emission towards MONEY_SUPPLY, no tail emission.\n"
    "    // Once the cap is reached the block reward is 0 and miners earn fees only.\n"
    "    const uint64_t remaining = already_generated_coins >= MONEY_SUPPLY ? 0 : MONEY_SUPPLY - already_generated_coins;\n"
    "    uint64_t base_reward = remaining >> emission_speed_factor;\n"
    "    if (base_reward == 0 && remaining > 0)\n"
    "      base_reward = remaining; // pay out the last dust so the cap is reached exactly\n"))

# miner tx must have at least one output even when reward + fees == 0
edit("src/cryptonote_core/cryptonote_tx_utils.cpp", sub(
    r"(      \[&out_amounts\]\(uint64_t a_dust\) \{ out_amounts.push_back\(a_dust\); \}\);\n)",
    r"\1    if (out_amounts.empty())\n      out_amounts.push_back(0); // post-cap block with no fees\n"))

# keep fees meaningful after emission ends
edit("src/cryptonote_core/blockchain.cpp", chain(
    sub(r"(    if \(!get_block_reward\(median, 1, already_generated_coins, base_reward, version\)\)\n      return false;\n)",
        r"\1    base_reward = std::max<uint64_t>(base_reward, FEE_REFERENCE_MIN_REWARD);\n"),
    sub(r"(    base_reward = BLOCK_REWARD_OVERESTIMATE;\n  \}\n)",
        r"\1  base_reward = std::max<uint64_t>(base_reward, FEE_REFERENCE_MIN_REWARD);\n"),
))

# --- 3. fresh hard-fork table -------------------------------------------------
def hf_table(name):
    t = C["LAUNCH_TIME"]
    return (f"const hardfork_t {name}_hard_forks[] = {{\n"
            f"  // {C['NAME']}: genesis + block 1 are v1, every current Monero feature (RandomX,\n"
            f"  // CLSAG, Bulletproofs+, view tags, ring size 16) is active from block 2.\n"
            f"  {{ 1, 1, 0, {t} }},\n  {{ 16, 2, 0, {t + 1} }},\n}};")
def patch_hf(s):
    for n in ["mainnet", "testnet", "stagenet"]:
        s = sub(rf"const hardfork_t {n}_hard_forks\[\] = \{{.*?\n\}};", hf_table(n), flags=re.S)(s)
        s = re.sub(rf"(const uint64_t {n}_hard_fork_version_1_till = )\d+;", r"\g<1>1;", s)
    return s
edit("src/hardforks/hardforks.cpp", patch_hf)

# --- 4. remove Monero checkpoints / seeds / DNS ------------------------------
edit("src/checkpoints/checkpoints.cpp", chain(
    sub(r"(bool checkpoints::init_default_checkpoints\(network_type nettype\)\n  \{\n).*?(\n  \}\n\n  bool checkpoints::load_checkpoints_from_json)",
        r"\1    // " + C["NAME"] + r": new chain - add your own checkpoints here once the chain is live\n    return true;\2", flags=re.S),
    sub(r'static const std::vector<std::string> dns_urls = \{.*?\};', "static const std::vector<std::string> dns_urls = { };", flags=re.S),
    sub(r'static const std::vector<std::string> testnet_dns_urls = \{.*?\};', "static const std::vector<std::string> testnet_dns_urls = { };", flags=re.S),
    sub(r'static const std::vector<std::string> stagenet_dns_urls = \{.*?\};', "static const std::vector<std::string> stagenet_dns_urls = { };", flags=re.S),
))
edit("src/blocks/blocks.cpp", sub(
    r"(const epee::span<const unsigned char> GetCheckpointsData\(cryptonote::network_type network\)\n  \{\n)",
    r"\1    return nullptr; // no precomputed Monero block hashes on this chain\n"))
for f in ["checkpoints.dat", "testnet_blocks.dat", "stagenet_blocks.dat"]:
    (ROOT / "src/blocks" / f).write_bytes(b"\x00")
edit("src/p2p/net_node.inl", sub(r'      full_addrs\.insert\("[0-9.]+:[0-9]+"\);\n', ""))
edit("src/p2p/net_node.h", sub(r'const std::vector<std::string> m_seed_nodes_list =\n\s*\{[^}]*\};',
     "const std::vector<std::string> m_seed_nodes_list =\n    { }; // add your DNS seed hostnames here"))
edit("src/common/updates.cpp", sub(r'static const std::vector<std::string> dns_urls = \{[^}]*\};',
     "static const std::vector<std::string> dns_urls = { };"))

# --- 5. names, units, binaries -------------------------------------------------
L, N, T, U = C["NAME_LOWER"], C["NAME"], C["TICKER"], C["UNIT_PREFIX"]
units = [("monero", L), ("millinero", "milli" + U), ("micronero", "micro" + U), ("nanonero", "nano" + U), ("piconero", "pico" + U)]
def rename_units(s):
    for a, b in units: s = s.replace(f'"{a}"', f'"{b}"')
    return s
edit("src/cryptonote_basic/cryptonote_format_utils.cpp", rename_units)

def patch_simplewallet(s):
    s = rename_units(s)
    s = s.replace("monero|millinero|micronero|nanonero|piconero", "|".join(b for _, b in units))
    s = s.replace("monero, millinero, micronero, nanonero, piconero", ", ".join(b for _, b in units))
    s = s.replace(" XMR", " " + T).replace("(donate.getmonero.org)", "")
    return s
edit("src/simplewallet/simplewallet.cpp", patch_simplewallet)

for d in ["src/daemon", "src/simplewallet", "src/wallet", "src/rpc", "src/cryptonote_core", "src/common", "src/p2p"]:
    for p in sorted((ROOT / d).glob("*.[ch]*")):
        txt = p.read_text(encoding="utf-8", errors="surrogateescape")
        new = "\n".join(
            re.sub(r"\bMonero\b", N, ln) if '"' in ln and "#include" not in ln and "Monero::" not in ln else ln
            for ln in txt.split("\n"))
        new = new.replace('"monero:', f'"{L}:')
        new = new.replace("uri.substr(0, 7)", f"uri.substr(0, {len(L) + 1})").replace("uri.substr(7)", f"uri.substr({len(L) + 1})")
        if new != txt:
            p.write_text(new, encoding="utf-8", errors="surrogateescape"); print(f"[rebrand] strings in {p.relative_to(ROOT)}")

for p in ROOT.joinpath("src").rglob("CMakeLists.txt"):
    txt = p.read_text()
    new = re.sub(r'OUTPUT_NAME "monero-', f'OUTPUT_NAME "{L}-', txt).replace('OUTPUT_NAME "monerod"', f'OUTPUT_NAME "{L}d"')
    if new != txt:
        p.write_text(new); print(f"[rebrand] binary names in {p.relative_to(ROOT)}")

edit("src/version.cpp.in", sub(r'#define DEF_MONERO_RELEASE_NAME "Fluorine Fermi"', f'#define DEF_MONERO_RELEASE_NAME "{N} Genesis"'))

print(f"\n[rebrand] done: {N} ({T}), max supply {C['MAX_SUPPLY']:,} {T}")
for n in ["mainnet", "testnet", "stagenet"]:
    print(f"  {n:8s} genesis tx: {genesis_tx_hex(n)}")
