// Verifies the Noxium hard cap against the real consensus function get_block_reward().
// Build: see tools/tests/README or the command used in tools/tests/run_supply_cap_test.sh
#include <cstdio>
#include "cryptonote_config.h"
#include "cryptonote_basic/cryptonote_basic_impl.h"

int main()
{
  using cryptonote::get_block_reward;
  const uint8_t v = 16;
  uint64_t r = 0, gen = 0;
  int failures = 0;
  auto check = [&](bool ok, const char* what) { std::printf("[%s] %s\n", ok ? "PASS" : "FAIL", what); if (!ok) ++failures; };

  // genesis + block 1 are v1 blocks (60 s target)
  get_block_reward(0, 0, 0, r, 1);  gen += r;
  get_block_reward(0, 0, gen, r, 1); gen += r;
  get_block_reward(0, 0, gen, r, v);
  std::printf("first v16 reward: %.12f\n", r / 1e12);
  check(r == 8583064754930ull, "first v16 block reward is ~8.583 NOX");

  // run the whole emission (63.6M blocks) and make sure the cap is hit exactly
  uint64_t blocks = 2;
  while (gen < MONEY_SUPPLY)
  {
    if (!get_block_reward(0, 0, gen, r, v)) { check(false, "get_block_reward failed"); return 1; }
    if (r == 0) break;
    gen += r; ++blocks;
  }
  std::printf("blocks until cap: %llu, total emitted: %.12f\n", (unsigned long long)blocks, gen / 1e12);
  check(gen == MONEY_SUPPLY, "total emission == MONEY_SUPPLY (18,000,000 NOX)");

  get_block_reward(0, 0, gen, r, v);
  check(r == 0, "reward is 0 once cap is reached (no tail emission)");
  get_block_reward(0, 0, MONEY_SUPPLY + 12345, r, v);
  check(r == 0, "reward is 0 even if already_generated exceeds the cap");
  return failures ? 1 : 0;
}
