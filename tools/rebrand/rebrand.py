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
    # Generated with python3 -c "import secrets; print(secrets.token_hex(16))"
    NETWORK_ID = dict(
        mainnet  = "33a5a39d4b3c1541f4d0abbbda002eb3",
        testnet  = "9defc17fb8bc7c1e04b4807097e920df",
        stagenet = "f01c7dc738def3829f1ed3e1e2beb2ef",
    ),
    # Random 256-bit value; the genesis keys are derived from it and thrown away
    GENESIS_SEED  = "Noxium genesis 2026-11-16 08fbfe03db39ea8c162a74dc6defb1034235eab9d386bfe232303204434d771d",
    # Hard-coded seed nodes ("ip:port"). Put the public IPs of your always-on nodes here.
    SEED_NODES = dict(
        mainnet  = [],   # e.g. "203.0.113.10:17750", "198.51.100.7:17750"
        testnet  = [],   # e.g. "203.0.113.10:27750"
        stagenet = [],
    ),
    # DNS seeds: hostnames with A/AAAA records pointing at your seed nodes (mainnet only)
    DNS_SEEDS = [],      # e.g. "seeds.noxium.org"
    TOR_SEEDS     = [],  # your nodes' "xxxx.onion:17753" addresses for --tx-proxy / anonymity zones
    I2P_SEEDS     = [],  # your nodes' "xxxx.b32.i2p" addresses
    DNS_BLOCKLIST = [],  # optional DNS blocklist domains you control (used with --enable-dns-blocklist)
    UPDATE_URL    = "https://updates.noxium.invalid/",    # set to your own release server
    DOWNLOAD_URL  = "https://downloads.noxium.invalid/",
    # Checkpoints {height: "block hash"} – add once the chain is live
    CHECKPOINTS = dict(mainnet={}, testnet={}, stagenet={}),
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
def _decompress(y):
    """Return the curve point with this y (even x) or None if y is not on the curve."""
    if y >= _q: return None
    xx = (y*y - 1) * pow(_d*y*y + 1, _q - 2, _q) % _q
    x = pow(xx, (_q + 3) // 8, _q)
    if (x*x - xx) % _q: x = x * _I % _q
    if (x*x - xx) % _q: return None
    if x & 1: x = _q - x
    return (x, y, 1, x * y % _q)
def _is_identity(P):
    x, y, z, _ = P
    return x % _q == 0 and (y - z) % _q == 0
def _nums_point(tag):
    """Nothing-up-my-sleeve point: hash-to-y, decompress, multiply by the cofactor 8.
    Nobody knows its discrete log, so an output sent to it can never be spent."""
    ctr = 0
    while True:
        h = hashlib.sha512(f"{CONFIG['GENESIS_SEED']}|{tag}|{ctr}".encode()).digest()
        P = _decompress(int.from_bytes(h[:32], "little") & ((1 << 255) - 1))
        if P is not None:
            P8 = _mul(8, P)
            if not _is_identity(P8) and _is_identity(_mul(_l, P8)):
                return _enc(P8)
        ctr += 1

def _varint(n):
    out = b""
    while n >= 0x80: out += bytes([(n & 0x7f) | 0x80]); n >>= 7
    return out + bytes([n])

def genesis_tx_hex(net):
    """Genesis coinbase: v1 tx, unlock 60, one output to a nothing-up-my-sleeve point
    (unknown discrete log), so the genesis reward is provably unspendable."""
    supply = CONFIG["MAX_SUPPLY"] * 10**12
    amount = supply >> CONFIG["EMISSION_SPEED_FACTOR"]   # same formula as get_block_reward() for a v1 block
    out_key = _nums_point("genesis-burn-output|" + net)
    tx_pub  = _nums_point("genesis-tx-pubkey|" + net)
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
            f"  // {C['NAME']}: only the genesis block is v1; every current Monero feature (RandomX,\n"
            f"  // CLSAG, Bulletproofs+, view tags, ring size 16) is active from block 1.\n"
            f"  {{ 1, 0, 0, {t} }},\n  {{ 16, 1, 0, {t + 1} }},\n}};")
def patch_hf(s):
    for n in ["mainnet", "testnet", "stagenet"]:
        s = sub(rf"const hardfork_t {n}_hard_forks\[\] = \{{.*?\n\}};", hf_table(n), flags=re.S)(s)
        s = re.sub(rf"(const uint64_t {n}_hard_fork_version_1_till = )\d+;", r"\g<1>0;", s)
    return s
edit("src/hardforks/hardforks.cpp", patch_hf)

def checkpoint_code():
    def adds(net):
        return "".join(f'      ADD_CHECKPOINT({h}, "{v}");\n' for h, v in sorted(C["CHECKPOINTS"][net].items()))
    return (f"    // {C['NAME']} checkpoints (configured in tools/rebrand/rebrand.py -> CHECKPOINTS)\n"
            "    if (nettype == TESTNET)\n    {\n" + adds("testnet") + "      return true;\n    }\n"
            "    if (nettype == STAGENET)\n    {\n" + adds("stagenet") + "      return true;\n    }\n"
            "    if (nettype == MAINNET)\n    {\n" + adds("mainnet") + "    }\n    return true;")

# --- 4. remove Monero checkpoints / seeds / DNS ------------------------------
edit("src/checkpoints/checkpoints.cpp", chain(
    sub(r"(bool checkpoints::init_default_checkpoints\(network_type nettype\)\n  \{\n).*?(\n  \}\n\n  bool checkpoints::load_checkpoints_from_json)",
        lambda m: m.group(1) + checkpoint_code() + m.group(2), flags=re.S),
    sub(r'static const std::vector<std::string> dns_urls = \{.*?\};', "static const std::vector<std::string> dns_urls = { };", flags=re.S),
    sub(r'static const std::vector<std::string> testnet_dns_urls = \{.*?\};', "static const std::vector<std::string> testnet_dns_urls = { };", flags=re.S),
    sub(r'static const std::vector<std::string> stagenet_dns_urls = \{.*?\};', "static const std::vector<std::string> stagenet_dns_urls = { };", flags=re.S),
))
edit("src/blocks/blocks.cpp", sub(
    r"(const epee::span<const unsigned char> GetCheckpointsData\(cryptonote::network_type network\)\n  \{\n)",
    r"\1    return nullptr; // no precomputed Monero block hashes on this chain\n"))
for f in ["checkpoints.dat", "testnet_blocks.dat", "stagenet_blocks.dat"]:
    (ROOT / "src/blocks" / f).write_bytes(b"\x00")
def seed_fn():
    def ins(net):
        return "".join(f'      full_addrs.insert("{a}");\n' for a in C["SEED_NODES"][net])
    return ("std::set<std::string> node_server<t_payload_net_handler>::get_ip_seed_nodes() const\n  {\n"
            "    std::set<std::string> full_addrs;\n"
            f"    // {C['NAME']} seed nodes (configured in tools/rebrand/rebrand.py -> SEED_NODES)\n"
            "    if (m_nettype == cryptonote::TESTNET)\n    {\n" + ins("testnet") + "    }\n"
            "    else if (m_nettype == cryptonote::STAGENET)\n    {\n" + ins("stagenet") + "    }\n"
            "    else if (m_nettype == cryptonote::FAKECHAIN)\n    {\n    }\n"
            "    else\n    {\n" + ins("mainnet") + "    }\n    return full_addrs;\n  }")
edit("src/p2p/net_node.inl", sub(r"std::set<std::string> node_server<t_payload_net_handler>::get_ip_seed_nodes\(\) const\n  \{.*?return full_addrs;\n  \}",
     lambda m: seed_fn(), flags=re.S))
edit("src/p2p/net_node.h", sub(r'const std::vector<std::string> m_seed_nodes_list =\n\s*\{[^}]*\};',
     lambda m: "const std::vector<std::string> m_seed_nodes_list =\n    { " + ", ".join(f'"{h}"' for h in C["DNS_SEEDS"]) + " }; // DNS seeds (rebrand.py -> DNS_SEEDS)"))
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

# --- 6. security fixes (from the consensus review, see SECURITY_REVIEW.md) -----
# C1: Monero's hard-coded PoW hash for its block 202612 would apply to our chain too
edit("src/cryptonote_core/cryptonote_tx_utils.cpp", sub(
    r'    // block 202612 bug workaround\n    if \(height == 202612\)\n    \{\n.*?\n      return true;\n    \}\n', "", flags=re.S))
edit("src/cryptonote_basic/cryptonote_format_utils.cpp", sub(
    r'(    if \(!hash_result\)\n      return false;\n\n)    if \(b\.miner_tx\.vin\.size\(\) == 1.*?\n    return hash_result;',
    r'\1    return true; // ' + C["NAME"] + ': no Monero block-202612 id exception', flags=re.S))

# M3: alt-chain already_generated_coins must not include fees
edit("src/cryptonote_core/blockchain.cpp", chain(
    sub(r'send_miner_notifications\(new_height, seedhash, prev_id, alt_chain\.back\(\)\.already_generated_coins\);',
        'send_miner_notifications(new_height, seedhash, prev_id, m_db->get_block_already_generated_coins(new_height - 1));'),
    sub(r'(    uint64_t block_reward = get_outs_money_amount\(b\.miner_tx\);\n    const uint64_t prev_generated_coins = [^\n]*\n)',
        r'\1    {\n      // coinbase = subsidy + fees; only the subsidy counts towards the emission. The un-penalised\n'
        r'      // subsidy is an upper bound for it, which is exact unless the block is over the median weight.\n'
        r'      uint64_t full_subsidy = 0;\n'
        r'      if (get_block_reward(0, 0, prev_generated_coins, full_subsidy, b.major_version))\n'
        r'        block_reward = std::min(block_reward, full_subsidy);\n    }\n'),
))

# L1: no assert abort when base_reward == 0 (debug builds after the cap)
edit("src/cryptonote_basic/cryptonote_basic_impl.cpp", sub(
    r'(      MERROR\("Block cumulative weight is too big: ".*?\n      return false;\n    \}\n)',
    r'\1\n    if (base_reward == 0) { // post-cap: nothing to penalise\n      reward = 0;\n      return true;\n    }\n', flags=re.S))

# L2: Monero Tor/I2P seeds and DNS blocklist
edit("src/p2p/net_node.inl", chain(
    sub(r'(    case epee::net_utils::zone::tor:\n      if \(m_nettype == cryptonote::MAINNET\)\n      \{\n        return \{\n)[^}]*(\};)',
        lambda m: m.group(1) + "".join(f'          "{a}",\n' for a in C["TOR_SEEDS"]) + "        " + m.group(2)),
    sub(r'(    case epee::net_utils::zone::i2p:\n      if \(m_nettype == cryptonote::MAINNET\)\n      \{\n        return \{\n)[^}]*(\};)',
        lambda m: m.group(1) + "".join(f'          "{a}",\n' for a in C["I2P_SEEDS"]) + "        " + m.group(2)),
    sub(r'static const std::vector<std::string> dns_urls = \{\n      "blocklist\.moneropulse\.se".*?\};',
        lambda m: "static const std::vector<std::string> dns_urls = { " + ", ".join(f'"{h}"' for h in C["DNS_BLOCKLIST"]) + " };", flags=re.S),
))

# L3: own message-signing domain separator
edit("src/cryptonote_config.h", sub(r'HASH_KEY_MESSAGE_SIGNING\[\] = "MoneroMessageSignature"',
     f'HASH_KEY_MESSAGE_SIGNING[] = "{N}MessageSignature"'))

# L4: OpenAlias tag + address-length checks, CSV export width
edit("src/common/dns_utils.cpp", sub(
    r'  // make sure the txt record has "oa1:xmr" and find it\n  auto pos = s\.find\("oa1:xmr"\);(.*?)    // length of address == 95.*?\n  \}\n  return \{\};',
    lambda m: f'  // make sure the txt record has "oa1:{T.lower()}" and find it\n  auto pos = s.find("oa1:{T.lower()}");' + m.group(1) +
    '    // the caller parses/validates the address; just sanity-check the length\n'
    '    if (pos2 - pos >= 90 && pos2 - pos <= 120)\n      return s.substr(pos, pos2 - pos);\n  }\n  return {};', flags=re.S))
edit("src/simplewallet/simplewallet.cpp", lambda t: t.replace("%106.106s", "%s"))

# L5: update checks off by default, no Monero download URLs
edit("src/cryptonote_core/cryptonote_core.cpp", sub(
    r'(  , "Check for new versions of )monero(: \[disabled\|notify\|download\|update\]"\n  , )"notify"',
    r'\g<1>' + L + r'\2"disabled"'))
edit("src/common/updates.cpp", sub(r'"https://downloads\.getmonero\.org/" : "https://updates\.getmonero\.org/"',
     f'"{C["DOWNLOAD_URL"]}" : "{C["UPDATE_URL"]}"'))

# L6: hardware wallets speak Monero's protocol/prefixes -> disabled
edit("src/device/device.cpp", sub(r'        #ifdef WITH_DEVICE_LEDGER\n        hw::ledger::register_all\(registry\);\n        #endif\n',
     f'        // {N}: Ledger/Trezor firmware only knows Monero address prefixes -> hardware wallets disabled\n'))
edit("cmake/CheckTrezor.cmake", sub(r'OPTION\(USE_DEVICE_TREZOR "Trezor support compilation" ON\)',
     'OPTION(USE_DEVICE_TREZOR "Trezor support compilation (off: firmware only knows Monero)" OFF)'))

# wallet: hard-fork tables may skip versions (1 -> 16), look entries up by version
edit("src/wallet/wallet2.cpp", sub(
    r'  wallet_is_outdated = static_cast<size_t>\(hf_version\) > wallet_num_hard_forks;\n.*?\n  daemon_is_outdated = height < start_height \|\| height >= end_height;\n',
    '  wallet_is_outdated = hf_version > wallet_hard_forks[wallet_num_hard_forks - 1].version;\n'
    '  if (wallet_is_outdated)\n    return;\n\n'
    '  // ' + N + ': the fork table may skip versions (1 -> 16), so look the entry up by version\n'
    '  size_t idx = wallet_num_hard_forks;\n'
    '  for (size_t n = 0; n < wallet_num_hard_forks; ++n)\n'
    '    if (wallet_hard_forks[n].version == hf_version)\n      idx = n;\n'
    '  if (idx == wallet_num_hard_forks)\n  {\n    daemon_is_outdated = true;\n    return;\n  }\n\n'
    '  // check block\'s height falls within wallet\'s expected range for block\'s given version\n'
    '  uint64_t start_height = hf_version == 1 ? 0 : wallet_hard_forks[idx].height;\n'
    '  uint64_t end_height = idx + 1 >= wallet_num_hard_forks\n'
    '    ? std::numeric_limits<uint64_t>::max()\n'
    '    : wallet_hard_forks[idx + 1].height;\n\n'
    '  daemon_is_outdated = height < start_height || height >= end_height;\n', flags=re.S))

print(f"\n[rebrand] done: {N} ({T}), max supply {C['MAX_SUPPLY']:,} {T}")
for n in ["mainnet", "testnet", "stagenet"]:
    print(f"  {n:8s} genesis tx: {genesis_tx_hex(n)}")
