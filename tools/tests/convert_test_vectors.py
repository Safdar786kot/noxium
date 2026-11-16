#!/usr/bin/env python3
"""Rewrite Monero test vectors in tests/ to Noxium equivalents.
Every Monero address is decoded and re-encoded with the Noxium prefix for the same
network/type (same keys, new prefix and checksum), so the tests still check the same keys."""
import re, sys, pathlib
from Crypto.Hash import keccak

ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
FULL = [0, 2, 3, 5, 6, 7, 9, 10, 11]  # encoded size per input block size
# Monero prefix -> Noxium prefix (see CONFIG["PREFIX"] in tools/rebrand/rebrand.py)
MAP = {18: 0x1c83, 19: 0x6381, 42: 0x5a82,      # mainnet std / integrated / subaddress
       53: 0x0ea1, 54: 0x561f, 63: 0x4d20,      # testnet
       24: 0x119b, 25: 0x5919, 36: 0x4f9a}      # stagenet

def k(b): h = keccak.new(digest_bits=256); h.update(b); return h.digest()
def b58enc(data):
    out = ""
    for i in range(0, len(data), 8):
        blk = data[i:i+8]; n = int.from_bytes(blk, "big"); s = ""
        for _ in range(FULL[len(blk)]): n, r = divmod(n, 58); s = ALPH[r] + s
        out += s
    return out
def b58dec(s):
    out = b""
    for i in range(0, len(s), 11):
        blk = s[i:i+11]; size = FULL.index(len(blk)); n = 0
        for c in blk: n = n * 58 + ALPH.index(c)
        out += n.to_bytes(size, "big")
    return out
def varint(n):
    out = b""
    while n >= 0x80: out += bytes([(n & 0x7f) | 0x80]); n >>= 7
    return out + bytes([n])
def unvarint(b):
    n = shift = i = 0
    while True:
        n |= (b[i] & 0x7f) << shift; shift += 7; i += 1
        if not b[i-1] & 0x80: return n, b[i:]

def convert(addr):
    try: raw = b58dec(addr)
    except (ValueError, OverflowError): return None
    body, chk = raw[:-4], raw[-4:]
    if k(body)[:4] != chk: return None
    prefix, rest = unvarint(body)
    if prefix not in MAP: return None
    nb = varint(MAP[prefix]) + rest
    return b58enc(nb + k(nb)[:4])

ADDR = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{95}(?:[1-9A-HJ-NP-Za-km-z]{11})?(?![1-9A-HJ-NP-Za-km-z])")
def fix_text(t):
    n = 0
    def rep(m):
        nonlocal n
        c = convert(m.group(0))
        if c: n += 1; return c
        return m.group(0)
    return ADDR.sub(rep, t), n

if __name__ == "__main__":
    total = 0
    for p in map(pathlib.Path, sys.argv[1:]):
        t, n = fix_text(p.read_text())
        if n: p.write_text(t); print(f"{p}: {n} addresses"); total += n
    print("converted", total)
