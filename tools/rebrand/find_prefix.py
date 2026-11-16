#!/usr/bin/env python3
"""Find CryptoNote base58 address prefixes whose addresses always start with given 2 chars.
Usage: find_prefix.py Nx Ni Ns"""
import sys
A = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
SIZES = [0, 2, 3, 5, 6, 7, 9, 10, 11]
def enc_block(b):
    n, s = int.from_bytes(b, "big"), ""
    for _ in range(SIZES[len(b)]): s = A[n % 58] + s; n //= 58
    return s
def b58(d): return "".join(enc_block(d[i:i + 8]) for i in range(0, len(d), 8))
def varint(n):
    o = b""
    while n >= 0x80: o += bytes([(n & 0x7f) | 0x80]); n >>= 7
    return o + bytes([n])
want = {w: None for w in sys.argv[1:] or ["Nx", "Ni", "Ns"]}
for p in range(0x80, 0x200000):
    # 64-byte keys (standard/subaddress) and 72-byte (integrated) – check both extremes
    firsts = {b58(varint(p) + fill * n)[:2] for n in (68, 76) for fill in (b"\x00", b"\xff")}
    if len(firsts) == 1 and (f := firsts.pop()) in want and want[f] is None:
        want[f] = p
    if all(v is not None for v in want.values()): break
for k, v in want.items(): print(k, hex(v) if v is not None else "not found")
