GOOSE ?= .toolchain/goose/build/goose
CC ?= gcc
SANITIZER_CC ?= gcc
BENCH_ITERATIONS ?= 1000
FUZZ_CC ?= clang
FUZZ_SECONDS ?= 120
FUZZ_RUNS ?= 100000
FUZZ_SEEDS ?= 20261107,20261108
FUZZ_COVERAGE ?= 30
.NOTPARALLEL:
.PHONY: setup format check test property sanitize fuzz mutation bench

setup:
	./scripts/setup-goose.sh

format:
	python3 scripts/native-manifest.py
	"$(GOOSE)" format b64.goose b64_accel.goose tests examples bench

check:
	python3 scripts/native-manifest.py --check
	"$(GOOSE)" format --check b64.goose b64_accel.goose tests examples bench
	"$(GOOSE)" check b64.goose
	"$(GOOSE)" check b64_accel.goose
	"$(GOOSE)" check tests/api.goose
	"$(GOOSE)" check tests/accelerated.goose
	"$(GOOSE)" check tests/stdlib_parity.goose
	"$(GOOSE)" check tests/oracle.goose
	"$(GOOSE)" check tests/alias_decode_lifetime.goose
	"$(GOOSE)" check tests/fuzz.goose
	"$(GOOSE)" check examples/basic_auth.goose
	"$(GOOSE)" check examples/json_binary.goose
	"$(GOOSE)" check bench/bench.goose
	"$(GOOSE)" check bench/strict.goose
	"$(GOOSE)" check bench/strict_equivalence.goose
	python3 -m py_compile tests/oracle.py bench/measure.py scripts/*.py
	git diff --check

test:
	mkdir -p .build
	python3 tests/native_cache.py "$(GOOSE)" "$(CC)"
	"$(GOOSE)" run tests/api.goose
	"$(GOOSE)" run tests/accelerated.goose
	"$(GOOSE)" run tests/stdlib_parity.goose
	"$(GOOSE)" run tests/alias_decode_lifetime.goose
	"$(GOOSE)" run examples/basic_auth.goose
	"$(GOOSE)" run examples/json_binary.goose
	"$(GOOSE)" build tests/api.goose --cc "$(CC)" -O2 -o .build/api
	./.build/api
	"$(GOOSE)" build tests/api.goose --cc "$(CC)" --debug --no-bce -o .build/api-debug
	./.build/api-debug
	GOOSE="$(GOOSE)" ./tests/alias_rejected.sh
	"$(GOOSE)" build tests/oracle.goose --cc "$(CC)" -O2 -o .build/oracle
	python3 tests/oracle.py .build/oracle

property:
	mkdir -p .build
	"$(GOOSE)" build tests/oracle.goose --cc "$(CC)" --debug --no-bce -o .build/oracle-debug
	python3 tests/oracle.py .build/oracle-debug
	"$(GOOSE)" build tests/stdlib_parity.goose --cc "$(CC)" --debug --no-bce -o .build/parity-debug
	./.build/parity-debug

sanitize:
	mkdir -p .build
	SANITIZER_CC="$(SANITIZER_CC)" "$(GOOSE)" build tests/api.goose --cc "$(abspath scripts/sanitizer-cc.sh)" --standalone --debug --no-bce -o .build/api-sanitize
	ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/api-sanitize
	SANITIZER_CC="$(SANITIZER_CC)" "$(GOOSE)" build tests/oracle.goose --cc "$(abspath scripts/sanitizer-cc.sh)" --standalone -O2 --no-bce -o .build/oracle-sanitize
	ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 UBSAN_OPTIONS=halt_on_error=1 python3 tests/oracle.py .build/oracle-sanitize
	SANITIZER_CC="$(SANITIZER_CC)" "$(GOOSE)" build examples/basic_auth.goose --cc "$(abspath scripts/sanitizer-cc.sh)" --standalone --debug --no-bce -o .build/basic-auth-sanitize
	ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/basic-auth-sanitize
	SANITIZER_CC="$(SANITIZER_CC)" "$(GOOSE)" build examples/json_binary.goose --cc "$(abspath scripts/sanitizer-cc.sh)" --standalone --debug --no-bce -o .build/json-binary-sanitize
	ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/json-binary-sanitize
	SANITIZER_CC="$(SANITIZER_CC)" "$(GOOSE)" build tests/alias_decode_lifetime.goose --cc "$(abspath scripts/sanitizer-cc.sh)" --standalone --debug --no-bce -o .build/alias-decode-sanitize
	ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/alias-decode-sanitize
	SANITIZER_CC="$(SANITIZER_CC)" "$(GOOSE)" build tests/accelerated.goose --cc "$(abspath scripts/sanitizer-cc.sh)" --standalone -O1 --no-bce -o .build/accelerated-sanitize
	ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/accelerated-sanitize

# Bounded libFuzzer + ASan/UBSan campaign on the real API. It proves both
# failure paths first (a Goose assertion retained by the fuzzer, and a
# deliberate overread caught by ASan), then requires every seed to reach
# FUZZ_RUNS executions and FUZZ_SECONDS seconds. Keep .build/fuzz/campaign.json
# with its corpus and logs.
fuzz:
	python3 scripts/fuzz.py --goose "$(GOOSE)" --cc "$(FUZZ_CC)" \
		--seconds "$(FUZZ_SECONDS)" --min-runs "$(FUZZ_RUNS)" \
		--seeds "$(FUZZ_SEEDS)" --coverage "$(FUZZ_COVERAGE)"

# Mutation-test the documented guarantees. The suite must pass on the pristine
# tree and fail on every mutant; a survivor is a test gap and fails the target.
mutation:
	python3 scripts/mutation-test.py --goose "$(GOOSE)"

# Run this target alone, with no other CPU work on the machine, and keep the
# recorded JSON with its provenance. It goes through bench/campaign.sh so the
# frozen baseline, the equal-contract competitor and the external comparators
# are all built and raced the same way as in a recorded campaign.
bench:
	mkdir -p .build
	GOOSE="$(GOOSE)" CC="$(CC)" BENCH_ITERATIONS="$(BENCH_ITERATIONS)" \
		./bench/campaign.sh .build/benchmark.json
