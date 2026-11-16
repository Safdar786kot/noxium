#!/bin/sh
# Run after building (build/release). Compiles and runs the supply-cap test against the built consensus libraries.
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd); B=$ROOT/build/release
LIBS="$(find $B/src $B/contrib $B/external -name '*.a' | grep -v -e /wallet/libwallet -e daemon -e simplewallet -e blockchain_utilities | tr '\n' ' ') $(find $B/monero_crypto_src -name '*.o' | tr '\n' ' ')"
g++ -std=c++17 -O2 -I$ROOT/src -I$ROOT/contrib/epee/include -I$ROOT/external/easylogging++ -I$B/generated_include \
  $ROOT/tools/tests/supply_cap_test.cpp -o /tmp/supply_cap_test -Wl,--start-group $LIBS -Wl,--end-group \
  -lboost_thread -lboost_filesystem -lboost_chrono -lboost_program_options -lboost_serialization -lboost_locale \
  -lssl -lcrypto -lsodium -lunbound -lhidapi-libusb -lusb-1.0 -lzmq -lprotobuf -lunwind -llzma -lreadline -lpthread
/tmp/supply_cap_test
