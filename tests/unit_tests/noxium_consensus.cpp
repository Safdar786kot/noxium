// Noxium-specific consensus regression tests (see SECURITY_REVIEW.md)
#include "gtest/gtest.h"
#include "string_tools.h"
#include "cryptonote_basic/cryptonote_format_utils.h"
#include "cryptonote_core/cryptonote_tx_utils.h"
#include "cryptonote_config.h"
#include "hardforks/hardforks.h"

using namespace cryptonote;

// C1: Monero hard-coded the PoW hash of its block 202612. That must not apply here,
// otherwise any blob would pass PoW at height 202612.
TEST(noxium_consensus, pow_at_202612_depends_on_blob)
{
  const std::string monero_longhash = "84f64766475d51837ac9efbef1926486e58563c95a19fef4aec3254f03000000";
  blobdata a(76, '\x01'), b(76, '\x02');
  crypto::hash ha, hb;
  ASSERT_TRUE(get_block_longhash(NULL, a, ha, 202612, 1, NULL, 0));
  ASSERT_TRUE(get_block_longhash(NULL, b, hb, 202612, 1, NULL, 0));
  ASSERT_NE(ha, hb);
  ASSERT_NE(epee::string_tools::pod_to_hex(ha), monero_longhash);
  ASSERT_NE(epee::string_tools::pod_to_hex(hb), monero_longhash);
}

// H1: only the genesis block is v1, everything from block 1 is v16.
TEST(noxium_consensus, hard_fork_table)
{
  ASSERT_EQ(num_mainnet_hard_forks, 2u);
  ASSERT_EQ(mainnet_hard_forks[0].version, 1);
  ASSERT_EQ(mainnet_hard_forks[0].height, 0u);
  ASSERT_EQ(mainnet_hard_forks[1].version, 16);
  ASSERT_EQ(mainnet_hard_forks[1].height, 1u);
  ASSERT_EQ(testnet_hard_forks[1].height, 1u);
  ASSERT_EQ(stagenet_hard_forks[1].height, 1u);
}

// M1 / supply: the genesis block parses and its reward is supply >> 22 (v1 rules).
TEST(noxium_consensus, genesis_reward)
{
  block bl;
  ASSERT_TRUE(generate_genesis_block(bl, config::GENESIS_TX, config::GENESIS_NONCE));
  ASSERT_EQ(bl.major_version, 1);
  ASSERT_EQ(get_outs_money_amount(bl.miner_tx), MONEY_SUPPLY >> EMISSION_SPEED_FACTOR_PER_MINUTE);
}
