#!/usr/bin/env python3
"""Simulate the Noxium emission curve (mirrors get_block_reward()).
Usage: emission.py [max_supply] [EMISSION_SPEED_FACTOR_PER_MINUTE]"""
import sys
SUPPLY = int(float(sys.argv[1]) if len(sys.argv) > 1 else 18_000_000) * 10**12
ESF = int(sys.argv[2]) if len(sys.argv) > 2 else 22
COIN, BLOCKS_PER_YEAR = 10**12, 365 * 24 * 30          # 2-minute blocks
gen = SUPPLY >> ESF                                     # genesis (v1 block, burned)
gen += (SUPPLY - gen) >> ESF                            # block 1 (v1, 60s target formula)
h, marks = 2, [0.5, 0.9, 0.99, 0.999, 1.0]
print(f"max supply {SUPPLY/COIN:,.0f}  first v16 block reward {((SUPPLY-gen)>>(ESF-1))/COIN:.6f}")
while marks:
    rem = SUPPLY - gen
    r = rem >> (ESF - 1) or rem
    gen += r; h += 1
    if gen >= marks[0] * SUPPLY:
        print(f"{marks.pop(0)*100:6.1f}% mined at height {h:>10,} (~{h/BLOCKS_PER_YEAR:6.1f} years)")
assert gen == SUPPLY
print("total emitted == MONEY_SUPPLY:", gen == SUPPLY)
