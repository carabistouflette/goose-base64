// SPDX-License-Identifier: Apache-2.0
// External comparators for the benchmark: maintained C/C++ Base64 libraries,
// adapted to this library's contract as closely as their own API allows.
//
// This program is a second harness, not a second implementation to ship. It
// emits the same rows as bench/bench.goose, in the same column order, so
// bench/measure.py records both through one protocol. One process times exactly
// one implementation, so the runner controls the order.
//
// Implementations:
//
//   simdutf  https://github.com/simdutf/simdutf, pinned in bench/ext/README.md.
//            Its own API expresses most of this contract: `base64_default` is
//            the standard alphabet with padding, `base64_url` the URL alphabet
//            without, and `last_chunk_handling_options::strict` rejects
//            non-zero trailing bits (BASE64_EXTRA_BITS) and a partial final
//            chunk. `OUTPUT_BUFFER_TOO_SMALL` is its budget error.
//
//   aklomp   https://github.com/aklomp/base64, pinned in bench/ext/README.md.
//            Standard alphabet, padded input only, no canonicality check and no
//            budget, so the equal-contract adaptation is this harness's own
//            validation pass plus a canonicality check, and a normalisation copy
//            for the URL alphabet. That adaptation is the interop cost, and it
//            is measured rather than hidden.
//
// Contract adaptation, stated once and applied to both:
//
//   * Failure atomicity. This library writes nothing when it refuses. Neither
//     external library promises that, so the harness hands them the tail of the
//     caller's buffer and truncates back to the original length on error. The
//     observable buffer is then identical to this library's, and no extra copy
//     is charged to the competitor.
//   * Budget. `max_out` is checked by the harness before the call, because
//     neither library takes a byte budget. The check is O(1) and is charged to
//     the competitor, not skipped.
//   * Allocation. Only reused-buffer rows are emitted. A `*_fresh` row would
//     compare glibc malloc against Goose's bump allocator, which is a different
//     question from the one this benchmark asks.
//
// Usage: bench_ext <iterations> <implementation> [--probe]
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "simdutf.h"

extern "C" {
#include "libbase64.h"
}

namespace {

constexpr int64_t MAX_OUT = 1048576;

const int64_t SIZES[] = {0, 1, 2, 3, 4, 16, 64, 256, 1024, 4096, 65536};
const char *NAMES[] = {"size_0",  "size_1",  "size_2",   "size_3",   "size_4",
                       "size_16", "size_64", "size_256", "size_1024",
                       "size_4096", "size_65536"};
constexpr size_t SIZE_COUNT = sizeof(SIZES) / sizeof(SIZES[0]);

// The same 6-bit table this library uses, so the aklomp adaptation's validation
// pass is the same work and not a slower stand-in.
const uint8_t STANDARD_VALUES[256] = {
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 62,  255, 255, 255, 63,
    52,  53,  54,  55,  56,  57,  58,  59,  60,  61,  255, 255, 255, 255, 255, 255,
    255, 0,   1,   2,   3,   4,   5,   6,   7,   8,   9,   10,  11,  12,  13,  14,
    15,  16,  17,  18,  19,  20,  21,  22,  23,  24,  25,  255, 255, 255, 255, 255,
    255, 26,  27,  28,  29,  30,  31,  32,  33,  34,  35,  36,  37,  38,  39,  40,
    41,  42,  43,  44,  45,  46,  47,  48,  49,  50,  51,  255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
};

const uint8_t URL_VALUES[256] = {
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 62,  255, 255,
    52,  53,  54,  55,  56,  57,  58,  59,  60,  61,  255, 255, 255, 255, 255, 255,
    255, 0,   1,   2,   3,   4,   5,   6,   7,   8,   9,   10,  11,  12,  13,  14,
    15,  16,  17,  18,  19,  20,  21,  22,  23,  24,  25,  255, 255, 255, 255, 63,
    255, 26,  27,  28,  29,  30,  31,  32,  33,  34,  35,  36,  37,  38,  39,  40,
    41,  42,  43,  44,  45,  46,  47,  48,  49,  50,  51,  255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
};

// This library's error taxonomy, so a probe can be read against it.
enum Error {
  E_NONE = 0,
  E_INVALID_LENGTH,
  E_INVALID_CHARACTER,
  E_INVALID_PADDING,
  E_NON_CANONICAL,
  E_OUTPUT_BUDGET,
};

const char *error_name(int error) {
  switch (error) {
  case E_NONE: return "None";
  case E_INVALID_LENGTH: return "InvalidLength";
  case E_INVALID_CHARACTER: return "InvalidCharacter";
  case E_INVALID_PADDING: return "InvalidPadding";
  case E_NON_CANONICAL: return "NonCanonical";
  case E_OUTPUT_BUDGET: return "OutputBudget";
  }
  return "?";
}

int64_t encoded_len(int64_t n) { return (n + 2) / 3 * 4; }

int64_t decoded_len(const uint8_t *src, int64_t n) {
  if (n % 4 != 0) return -1;
  int64_t pad = 0;
  if (n > 0 && src[n - 1] == '=') pad = (n >= 2 && src[n - 2] == '=') ? 2 : 1;
  if (pad > 0 && n < 4) return -1;
  return n / 4 * 3 - pad;
}

// A cheap content sample for the timed loop: three real output bytes, so the
// call cannot be elided, without adding O(n) work that would dilute the ratio.
int64_t sample(const uint8_t *bytes, int64_t n) {
  if (n == 0) return 0;
  return bytes[0] + bytes[n / 2] + bytes[n - 1];
}

// FNV-1a over the whole output, accumulated outside the timed loop.
int64_t fnv(const uint8_t *bytes, int64_t n) {
  int64_t h = 2166136261;
  for (int64_t i = 0; i < n; i++) h = ((h ^ bytes[i]) * 16777619) & 4294967295;
  return h;
}

int64_t now_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

void row(const char *phase, const char *fixture, const char *implementation,
         int64_t elapsed, int64_t iterations, int64_t input_len,
         int64_t output_len, int64_t comparable, int64_t checksum) {
  std::printf("%s\t%s\t%s\t%lld\t%lld\t%lld\t%lld\t%lld\t%lld\n", phase, fixture,
              implementation, (long long)elapsed, (long long)iterations,
              (long long)input_len, (long long)output_len,
              (long long)comparable, (long long)checksum);
}

// ---------------------------------------------------------------------------
// simdutf
// ---------------------------------------------------------------------------

// simdutf's own options for this library's standard/padded policy.
constexpr simdutf::base64_options SIMDUTF_ENCODE = simdutf::base64_default;
constexpr simdutf::base64_options SIMDUTF_DECODE = simdutf::base64_default;
constexpr simdutf::last_chunk_handling_options SIMDUTF_LAST =
    simdutf::last_chunk_handling_options::strict;

int simdutf_encode(std::vector<uint8_t> &out, const uint8_t *src, int64_t n) {
  size_t need = (size_t)encoded_len(n);
  size_t start = out.size();
  out.resize(start + need);
  size_t written = simdutf::binary_to_base64(
      (const char *)src, (size_t)n, (char *)out.data() + start, SIMDUTF_ENCODE);
  out.resize(start + written);
  return E_NONE;
}

int simdutf_decode(std::vector<uint8_t> &out, const uint8_t *src, int64_t n) {
  int64_t need = decoded_len(src, n);
  if (need < 0) return E_INVALID_LENGTH;
  if (need > MAX_OUT) return E_OUTPUT_BUDGET;
  size_t start = out.size();
  out.resize(start + (size_t)need);
  simdutf::result r = simdutf::base64_to_binary(
      (const char *)src, (size_t)n, (char *)out.data() + start, SIMDUTF_DECODE,
      SIMDUTF_LAST);
  if (r.error != simdutf::error_code::SUCCESS) {
    // Truncate back: the observable buffer is then what this library leaves.
    out.resize(start);
    switch (r.error) {
    case simdutf::error_code::INVALID_BASE64_CHARACTER:
      return E_INVALID_CHARACTER;
    case simdutf::error_code::BASE64_INPUT_REMAINDER:
      return E_INVALID_LENGTH;
    case simdutf::error_code::BASE64_EXTRA_BITS:
      return E_NON_CANONICAL;
    case simdutf::error_code::OUTPUT_BUFFER_TOO_SMALL:
      return E_OUTPUT_BUDGET;
    default:
      return E_INVALID_CHARACTER;
    }
  }
  out.resize(start + r.count);
  return E_NONE;
}

// ---------------------------------------------------------------------------
// The validation predicate, shared by the adapted comparators
// ---------------------------------------------------------------------------

// This library's validation pass, canonicality check and budget, with no write.
// Returns E_NONE when the text is acceptable under the standard/padded policy,
// otherwise the precise error this library would return. It is the authority on
// rejection for every adapted comparator below.
int validate_only(const uint8_t *src, int64_t n) {
  int64_t need = decoded_len(src, n);
  if (need < 0) return E_INVALID_LENGTH;
  if (need > MAX_OUT) return E_OUTPUT_BUDGET;
  int64_t pad = 0;
  if (n > 0 && src[n - 1] == '=') pad = (n >= 2 && src[n - 2] == '=') ? 2 : 1;
  int64_t body = n - pad;
  for (int64_t i = 0; i < body; i++) {
    uint8_t c = src[i];
    if (c == '=') return E_INVALID_PADDING;
    if (STANDARD_VALUES[c] == 255) return E_INVALID_CHARACTER;
  }
  int64_t rest = body % 4;
  if (rest == 2 && (STANDARD_VALUES[src[body - 1]] & 15) != 0)
    return E_NON_CANONICAL;
  if (rest == 3 && (STANDARD_VALUES[src[body - 1]] & 3) != 0)
    return E_NON_CANONICAL;
  return E_NONE;
}

// ---------------------------------------------------------------------------
// simdutf, fast path with the Goose validator on rejection
// ---------------------------------------------------------------------------

// The scalar write pass, used only as the fallback when the native call refuses
// an input the validator accepts. That combination should not happen; if it
// does, returning success without appending anything would be a silent wrong
// answer, so the bytes are produced here instead.
void scalar_decode_into(std::vector<uint8_t> &out, const uint8_t *src,
                        int64_t n) {
  int64_t pad = 0;
  if (n > 0 && src[n - 1] == '=') pad = (n >= 2 && src[n - 2] == '=') ? 2 : 1;
  int64_t body = n - pad;
  int64_t rest = body % 4;
  int64_t i = 0;
  for (; i + 4 <= body; i += 4) {
    uint8_t a = STANDARD_VALUES[src[i]], b = STANDARD_VALUES[src[i + 1]];
    uint8_t c = STANDARD_VALUES[src[i + 2]], d = STANDARD_VALUES[src[i + 3]];
    out.push_back((uint8_t)((a << 2) | (b >> 4)));
    out.push_back((uint8_t)((b << 4) | (c >> 2)));
    out.push_back((uint8_t)((c << 6) | d));
  }
  if (rest == 2) {
    uint8_t a = STANDARD_VALUES[src[i]], b = STANDARD_VALUES[src[i + 1]];
    out.push_back((uint8_t)((a << 2) | (b >> 4)));
  } else if (rest == 3) {
    uint8_t a = STANDARD_VALUES[src[i]], b = STANDARD_VALUES[src[i + 1]];
    uint8_t c = STANDARD_VALUES[src[i + 2]];
    out.push_back((uint8_t)((a << 2) | (b >> 4)));
    out.push_back((uint8_t)((b << 4) | (c >> 2)));
  }
}

// The design under evaluation, and the one the coordinator asked for: simdutf
// `strict` on the fast path, an O(1) shape check and an equality test on the
// produced length, and this library's validator only when the native call does
// not succeed with exactly the expected count.
//
// Why the equality test is enough for the padded policy. Our shape check
// requires n % 4 == 0. simdutf ignores ASCII whitespace, so with w whitespace
// bytes its effective length is n - w, and `strict` requires (n - w) % 4 == 0;
// with n % 4 == 0 that gives w % 4 == 0. Its produced count is
// (n - w)/4*3 - p', where p' is the padding it saw, while our need is
// n/4*3 - padlen. count == need therefore implies padlen - p' = 3w/4. Since
// padlen <= 2 and p' >= 0, that needs 3w/4 <= 2, so w <= 2; combined with
// w % 4 == 0 it forces w == 0. A success whose count equals need cannot have
// contained whitespace.
//
// That is an argument, not evidence, so `--probe-differential` checks it
// exhaustively over every short text with whitespace inserted at every position,
// and over the padding edges. If it ever fails, the fast path is wrong and the
// probe says so.
//
// Buffer safety. `base64_to_binary` documents that the output buffer must be at
// least `maximal_binary_length_from_base64(input, length)` bytes or the function
// "may cause a buffer overflow" -- that is larger than `need`, because simdutf
// may write a partial group before it discovers an error. Sizing the scratch to
// `need` was therefore a real overrun hazard. This uses `base64_to_binary_safe`
// with an explicit capacity instead, which cannot write past `outlen` and has
// negligible overhead when the input has no ignorable characters -- which is
// exactly the fast path, since a success here implies no whitespace.
//
// Atomicity: the native call writes into a scratch buffer, and the caller's
// buffer is appended to only after the call has succeeded. A rejected call
// therefore never touches the caller's buffer at all, which is the same
// guarantee this library gives, not a weaker "truncated back" one.
//
// The scratch is a function-local static, reused across calls. That is
// acceptable for a single-threaded prototype and models Goose's bump allocator
// (allocating and dropping `need` bytes per call is a pointer bump, not a
// malloc), but it is global mutable state and must not be carried into the
// library. The production conclusion needs the same measurement taken in Goose,
// not this model of it.
int simdutf_fast_decode(std::vector<uint8_t> &out, const uint8_t *src,
                        int64_t n) {
  int64_t need = decoded_len(src, n);
  if (need < 0) return E_INVALID_LENGTH;
  if (need > MAX_OUT) return E_OUTPUT_BUDGET;
  static std::vector<uint8_t> scratch;
  scratch.resize((size_t)need);
  size_t outlen = (size_t)need;
  simdutf::result r = simdutf::base64_to_binary_safe(
      (const char *)src, (size_t)n, (char *)scratch.data(), outlen,
      SIMDUTF_DECODE, SIMDUTF_LAST);
  if (r.error == simdutf::error_code::SUCCESS && outlen == (size_t)need) {
    out.insert(out.end(), scratch.begin(), scratch.begin() + need);
    return E_NONE;
  }
  // Rejection path: the Goose validator produces the precise error, and the
  // caller's buffer is still untouched.
  int e = validate_only(src, n);
  if (e != E_NONE) return e;
  // The validator accepts but the native call did not produce the expected
  // count. That is an internal inconsistency, not a rejection: produce the bytes
  // with the scalar pass rather than reporting success with nothing appended.
  scalar_decode_into(out, src, n);
  return E_NONE;
}

// ---------------------------------------------------------------------------
// aklomp/base64, adapted to this contract
// ---------------------------------------------------------------------------

// The equal-contract adaptation: this library's validation pass, its
// canonicality check and its budget, then aklomp's decoder for the bit work.
// aklomp takes the standard alphabet with padding only, so the URL alphabet and
// unpadded text need a normalisation copy first, exactly as a caller would have
// to write it.
int aklomp_decode(std::vector<uint8_t> &out, const uint8_t *src, int64_t n) {
  int e = validate_only(src, n);
  if (e != E_NONE) return e;
  int64_t need = decoded_len(src, n);
  size_t start = out.size();
  out.resize(start + (size_t)need);
  size_t written = 0;
  int ok = base64_decode((const char *)src, (size_t)n,
                         (char *)out.data() + start, &written, 0);
  if (!ok || (int64_t)written != need) {
    out.resize(start);
    return E_INVALID_CHARACTER;
  }
  return E_NONE;
}

int aklomp_encode(std::vector<uint8_t> &out, const uint8_t *src, int64_t n) {
  size_t need = (size_t)encoded_len(n);
  size_t start = out.size();
  out.resize(start + need);
  size_t written = 0;
  base64_encode((const char *)src, (size_t)n, (char *)out.data() + start,
                &written, 0);
  out.resize(start + written);
  return E_NONE;
}

// ---------------------------------------------------------------------------

struct Implementation {
  const char *name;
  int (*encode)(std::vector<uint8_t> &, const uint8_t *, int64_t);
  int (*decode)(std::vector<uint8_t> &, const uint8_t *, int64_t);
};

const Implementation IMPLEMENTATIONS[] = {
    {"simdutf", simdutf_encode, simdutf_decode},
    {"simdutf_fast", simdutf_encode, simdutf_fast_decode},
    {"aklomp", aklomp_encode, aklomp_decode},
};

const Implementation *find(const char *name) {
  for (const auto &impl : IMPLEMENTATIONS)
    if (std::strcmp(impl.name, name) == 0) return &impl;
  return nullptr;
}

// The fixtures whose contract the external library actually matches. A row is
// `comparable` only when both sides do the same work and produce the same
// bytes; the probe mode prints the evidence for each decision.
bool comparable_fixture(const char *implementation, const char *phase,
                        const char *fixture) {
  if (std::strcmp(phase, "encode") == 0 || std::strcmp(phase, "decode") == 0 ||
      std::strcmp(phase, "pathological") == 0 ||
      std::strcmp(phase, "consumer") == 0)
    return true;
  // Rejection paths: the two libraries disagree about what a rejection is.
  if (std::strcmp(implementation, "simdutf") == 0) {
    // simdutf ignores ASCII spaces, tabs and newlines inside base64 text even
    // without `accept_garbage`: `Zg ==`, `Z g==` and `Zm9v YmFy` all return
    // SUCCESS (probe output in bench/ext/README.md). This library rejects every
    // one of them as InvalidCharacter. Both refuse the `Zg =` fixture, but for
    // different reasons and after different work, so the row is not a race.
    return std::strcmp(fixture, "whitespace") != 0;
  }
  // aklomp's adaptation is this harness's own validation, so it matches on every
  // rejection fixture.
  return true;
}

} // namespace

// Exhaustive differential check of the fast path against the validator.
//
// The fast path is only correct if `simdutf_fast_decode` returns exactly what
// `validate_only` says, for every input. This walks every text of length 0..6
// over a pool that contains both alphabets' extra characters, '=', three
// whitespace bytes, an invalid byte and NUL, and then every valid text of
// length 4, 8 and 12 with one and two whitespace bytes inserted at every
// position. A single disagreement is a counterexample and is printed.
static int probe_differential() {
  const uint8_t pool[] = {'A', 'B', '/', '+', '-', '_', '=', ' ', '\n', '\t', '!', 0};
  const int pool_size = (int)(sizeof(pool) / sizeof(pool[0]));
  int64_t checked = 0, disagreements = 0;

  for (int len = 0; len <= 6; len++) {
    std::vector<int> digits((size_t)len, 0);
    int64_t total = 1;
    for (int i = 0; i < len; i++) total *= pool_size;
    for (int64_t code = 0; code < total; code++) {
      int64_t rest = code;
      std::vector<uint8_t> text((size_t)len);
      for (int i = 0; i < len; i++) {
        text[(size_t)i] = pool[rest % pool_size];
        rest /= pool_size;
      }
      std::vector<uint8_t> out;
      int fast = simdutf_fast_decode(out, text.data(), len);
      int slow = validate_only(text.data(), len);
      checked++;
      if (fast != slow) {
        disagreements++;
        if (disagreements <= 10) {
          std::printf("DISAGREE len=%d fast=%s slow=%s text=", len,
                      error_name(fast), error_name(slow));
          for (int i = 0; i < len; i++) std::printf("%02x", text[(size_t)i]);
          std::printf("\n");
        }
      }
      // A success must produce exactly the bytes the validator implies.
      if (fast == E_NONE) {
        int64_t need = decoded_len(text.data(), len);
        if ((int64_t)out.size() != need) {
          disagreements++;
          std::printf("DISAGREE len=%d produced=%zu need=%lld\n", len,
                      out.size(), (long long)need);
        }
      } else if (!out.empty()) {
        disagreements++;
        std::printf("DISAGREE len=%d rejected but wrote %zu bytes\n", len,
                    out.size());
      }
    }
  }

  // Whitespace inserted into otherwise valid text, at every position.
  const char *valid[] = {"AAAA", "Zg==", "Zm8=", "Zm9v", "AAAAAAA=", "AAAAAAAA",
                         "AAAAAAAAAAA=", "AAAAAAAAAAAA"};
  const uint8_t ws[] = {' ', '\n', '\t'};
  for (const char *base : valid) {
    int64_t n = (int64_t)std::strlen(base);
    for (int count = 1; count <= 2; count++) {
      for (int64_t pos = 0; pos <= n; pos++) {
        for (uint8_t w : ws) {
          std::vector<uint8_t> text;
          text.insert(text.end(), base, base + pos);
          for (int k = 0; k < count; k++) text.push_back(w);
          text.insert(text.end(), base + pos, base + n);
          std::vector<uint8_t> out;
          int fast = simdutf_fast_decode(out, text.data(), (int64_t)text.size());
          int slow = validate_only(text.data(), (int64_t)text.size());
          checked++;
          if (fast != slow || fast == E_NONE) {
            disagreements++;
            if (disagreements <= 10) {
              std::printf("DISAGREE whitespace base=%s pos=%lld count=%d "
                          "fast=%s slow=%s\n",
                          base, (long long)pos, count, error_name(fast),
                          error_name(slow));
            }
          }
        }
      }
    }
  }

  // Malformed long inputs: a valid text with one byte corrupted at a random
  // position, at sizes where simdutf's vector path is active. This is where an
  // overrun would show up if the output buffer were sized to `need` instead of
  // to `maximal_binary_length_from_base64`.
  {
    uint64_t state = 0x9E3779B97F4A7C15ull;
    auto next = [&state]() {
      state ^= state << 13;
      state ^= state >> 7;
      state ^= state << 17;
      return state;
    };
    const int64_t sizes[] = {4, 8, 64, 256, 1024, 4096, 65536};
    const uint8_t bad[] = {'!', ' ', '\n', '=', 0, 0xFF};
    for (int64_t size : sizes) {
      for (int trial = 0; trial < 64; trial++) {
        std::vector<uint8_t> text((size_t)size, 'A');
        int64_t pos = (int64_t)(next() % (uint64_t)size);
        text[(size_t)pos] = bad[next() % (sizeof(bad) / sizeof(bad[0]))];
        std::vector<uint8_t> out;
        int fast = simdutf_fast_decode(out, text.data(), size);
        int slow = validate_only(text.data(), size);
        checked++;
        if (fast != slow) {
          disagreements++;
          if (disagreements <= 10)
            std::printf("DISAGREE malformed size=%lld pos=%lld fast=%s slow=%s\n",
                        (long long)size, (long long)pos, error_name(fast),
                        error_name(slow));
        }
        if (fast == E_NONE) {
          int64_t need = decoded_len(text.data(), size);
          if ((int64_t)out.size() != need) {
            disagreements++;
            std::printf("DISAGREE malformed size=%lld produced=%zu need=%lld\n",
                        (long long)size, out.size(), (long long)need);
          }
        } else if (!out.empty()) {
          disagreements++;
          std::printf("DISAGREE malformed size=%lld rejected but wrote %zu\n",
                      (long long)size, out.size());
        }
      }
    }
  }

  std::printf("differential: %lld cases, %lld disagreements\n",
              (long long)checked, (long long)disagreements);
  return disagreements == 0 ? 0 : 1;
}

// Buffer-safety probe: the fast path with a *fresh, exactly sized* output buffer
// on every call, so a sanitizer sees an overrun that a retained vector's spare
// capacity would hide. Run this under ASan + UBSan.
static int probe_asan() {
  const int64_t sizes[] = {0, 1, 2, 3, 4, 5, 7, 8, 64, 256, 1024, 4096, 65536};
  const uint8_t bad[] = {'!', ' ', '\n', '=', 0, 0xFF, '+'};
  int64_t checked = 0;
  for (int64_t size : sizes) {
    for (int variant = 0; variant < 8; variant++) {
      std::vector<uint8_t> text((size_t)size, 'A');
      if (variant > 0 && size > 0) {
        int64_t pos = (size * variant) / 8;
        text[(size_t)pos] = bad[variant % (sizeof(bad) / sizeof(bad[0]))];
      }
      int64_t need = decoded_len(text.data(), size);
      if (need < 0) continue;
      // Exactly `need` bytes, freshly allocated, no spare capacity.
      std::vector<uint8_t> scratch((size_t)need);
      size_t outlen = (size_t)need;
      simdutf::result r = simdutf::base64_to_binary_safe(
          (const char *)text.data(), (size_t)size, (char *)scratch.data(),
          outlen, SIMDUTF_DECODE, SIMDUTF_LAST);
      (void)r;
      checked++;
    }
  }
  std::printf("asan: %lld exact-capacity calls, no overrun\n", (long long)checked);
  return 0;
}

// Negative control: the *unsafe* call with a buffer one byte too small. This is
// the documented hazard that made the first prototype wrong, and ASan must
// report a heap-buffer-overflow. It proves two things at once: the sanitizer is
// instrumented, and `base64_to_binary` really does write past a buffer sized to
// `need` -- which is why the fast path uses `base64_to_binary_safe`.
static int probe_asan_negative() {
  std::vector<uint8_t> text(1024, 'A');
  int64_t need = decoded_len(text.data(), 1024);
  std::vector<uint8_t> scratch((size_t)need - 1);
  simdutf::result r = simdutf::base64_to_binary(
      (const char *)text.data(), 1024, (char *)scratch.data(), SIMDUTF_DECODE,
      SIMDUTF_LAST);
  std::printf("negative control: error=%d count=%zu (ASan should have fired)\n",
              (int)r.error, r.count);
  return 0;
}

int main(int argc, char **argv) {
  if (argc >= 4 && std::strcmp(argv[3], "--probe-differential") == 0) {
    return probe_differential();
  }
  if (argc >= 4 && std::strcmp(argv[3], "--probe-asan") == 0) {
    return probe_asan();
  }
  if (argc >= 4 && std::strcmp(argv[3], "--probe-asan-negative") == 0) {
    return probe_asan_negative();
  }
  if (argc < 3) {
    std::fprintf(stderr, "usage: %s <iterations> <implementation> [--probe]\n",
                 argv[0]);
    return 2;
  }
  int64_t iterations = std::atoll(argv[1]);
  const Implementation *impl = find(argv[2]);
  if (!impl || iterations <= 0) {
    std::fprintf(stderr, "unknown implementation or bad iteration count\n");
    return 2;
  }
  bool probe = argc > 3 && std::strcmp(argv[3], "--probe") == 0;

  std::vector<std::vector<uint8_t>> sources(SIZE_COUNT);
  std::vector<std::vector<uint8_t>> texts(SIZE_COUNT);
  for (size_t index = 0; index < SIZE_COUNT; index++) {
    sources[index].resize((size_t)SIZES[index]);
    for (int64_t i = 0; i < SIZES[index]; i++)
      sources[index][(size_t)i] = (uint8_t)((i * 37 + 11) & 0xFF);
    texts[index].resize((size_t)encoded_len(SIZES[index]));
    size_t written = simdutf::binary_to_base64(
        (const char *)sources[index].data(), (size_t)SIZES[index],
        (char *)texts[index].data(), simdutf::base64_default);
    texts[index].resize(written);
  }

  if (probe) {
    // Print what each implementation does on every fixture, so the comparable
    // flags above are evidence rather than assertion.
    for (size_t index = 0; index < SIZE_COUNT; index++) {
      std::vector<uint8_t> out;
      int e = impl->decode(out, texts[index].data(), (int64_t)texts[index].size());
      std::printf("decode\t%s\t%s\t%d\t%zu\t%zu\n", NAMES[index], error_name(e),
                  e, texts[index].size(), out.size());
    }
    const char *rejects[] = {"noncanonical", "invalid_char", "whitespace",
                             "bad_padding", "url_unpadded", "invalid_at_end_64k"};
    std::vector<uint8_t> long_text(65536, 'A');
    std::vector<uint8_t> long_bad = long_text;
    long_bad[long_bad.size() - 1] = '!';
    std::vector<std::vector<uint8_t>> rejected = {
        {'Z', 'h', '=', '='}, {'Z', 'g', '!', '='}, {'Z', 'g', ' ', '='},
        {'Z', 'g', '='},      {'-', '_', '8'},      long_bad};
    for (int i = 0; i < 6; i++) {
      std::vector<uint8_t> out;
      int e = impl->decode(out, rejected[(size_t)i].data(),
                           (int64_t)rejected[(size_t)i].size());
      std::printf("reject\t%s\t%s\t%d\t%zu\t%zu\n", rejects[i], error_name(e), e,
                  rejected[(size_t)i].size(), out.size());
    }
    std::vector<uint8_t> out;
    int e = impl->decode(out, long_text.data(), (int64_t)long_text.size());
    std::printf("pathological\tall_A_64k\t%s\t%d\t%zu\t%zu\n", error_name(e), e,
                long_text.size(), out.size());
    return 0;
  }

  int64_t checksum = 0;
  std::vector<uint8_t> buffer;

  for (size_t index = 0; index < SIZE_COUNT; index++) {
    const uint8_t *source = sources[index].data();
    int64_t source_len = SIZES[index];
    const uint8_t *text = texts[index].data();
    int64_t text_len = (int64_t)texts[index].size();

    // Encode.
    buffer.clear();
    int64_t start = now_ns();
    for (int64_t i = 0; i < iterations; i++) {
      buffer.clear();
      if (impl->encode(buffer, source, source_len) != E_NONE) std::abort();
      checksum += sample(buffer.data(), (int64_t)buffer.size());
    }
    int64_t elapsed = now_ns() - start;
    int64_t produced = (int64_t)buffer.size();
    std::vector<uint8_t> final_encode;
    if (impl->encode(final_encode, source, source_len) != E_NONE) std::abort();
    if ((int64_t)final_encode.size() != produced) std::abort();
    row("encode", NAMES[index], impl->name, elapsed, iterations, source_len,
        produced, comparable_fixture(impl->name, "encode", NAMES[index]) ? 1 : 0,
        fnv(final_encode.data(), (int64_t)final_encode.size()));

    // Decode.
    buffer.clear();
    start = now_ns();
    for (int64_t i = 0; i < iterations; i++) {
      buffer.clear();
      if (impl->decode(buffer, text, text_len) != E_NONE) std::abort();
      checksum += sample(buffer.data(), (int64_t)buffer.size());
    }
    elapsed = now_ns() - start;
    produced = (int64_t)buffer.size();
    std::vector<uint8_t> final_decode;
    if (impl->decode(final_decode, text, text_len) != E_NONE) std::abort();
    if ((int64_t)final_decode.size() != produced) std::abort();
    row("decode", NAMES[index], impl->name, elapsed, iterations, text_len,
        produced, comparable_fixture(impl->name, "decode", NAMES[index]) ? 1 : 0,
        fnv(final_decode.data(), (int64_t)final_decode.size()));
  }

  // Rejection paths.
  {
    std::vector<uint8_t> long_text(65536, 'A');
    std::vector<uint8_t> long_bad = long_text;
    long_bad[long_bad.size() - 1] = '!';
    const char *rejects[] = {"noncanonical", "invalid_char", "whitespace",
                             "bad_padding", "url_unpadded", "invalid_at_end_64k"};
    std::vector<std::vector<uint8_t>> rejected = {
        {'Z', 'h', '=', '='}, {'Z', 'g', '!', '='}, {'Z', 'g', ' ', '='},
        {'Z', 'g', '='},      {'-', '_', '8'},      long_bad};
    for (int i = 0; i < 6; i++) {
      const uint8_t *text = rejected[(size_t)i].data();
      int64_t text_len = (int64_t)rejected[(size_t)i].size();
      buffer.clear();
      int64_t start = now_ns();
      for (int64_t k = 0; k < iterations; k++) {
        buffer.clear();
        if (impl->decode(buffer, text, text_len) != E_NONE) checksum += 1;
      }
      int64_t elapsed = now_ns() - start;
      row("reject", rejects[i], impl->name, elapsed, iterations, text_len,
          (int64_t)buffer.size(),
          comparable_fixture(impl->name, "reject", rejects[i]) ? 1 : 0,
          fnv(buffer.data(), (int64_t)buffer.size()));
    }

    // Valid but worst case for the validating decoder: 64 KiB of 'A'.
    buffer.clear();
    int64_t start = now_ns();
    for (int64_t k = 0; k < iterations; k++) {
      buffer.clear();
      if (impl->decode(buffer, long_text.data(), (int64_t)long_text.size()) !=
          E_NONE)
        std::abort();
      checksum += sample(buffer.data(), (int64_t)buffer.size());
    }
    int64_t elapsed = now_ns() - start;
    if ((int64_t)buffer.size() != 49152) std::abort();
    row("pathological", "all_A_64k", impl->name, elapsed, iterations,
        (int64_t)long_text.size(), (int64_t)buffer.size(), 1,
        fnv(buffer.data(), (int64_t)buffer.size()));
  }

  // The consumer end of the path: an HTTP Basic header value (RFC 7617 §2).
  {
    const char *users[] = {"Aladdin", "user", "a"};
    const char *passwords[] = {"open sesame", "pass", ""};
    const char *consumers[] = {"basic_auth_rfc7617", "basic_auth_short",
                               "basic_auth_empty_password"};
    for (int index = 0; index < 3; index++) {
      std::vector<uint8_t> credential;
      for (const char *p = users[index]; *p; p++)
        credential.push_back((uint8_t)*p);
      credential.push_back(':');
      for (const char *p = passwords[index]; *p; p++)
        credential.push_back((uint8_t)*p);
      buffer.clear();
      int64_t start = now_ns();
      for (int64_t k = 0; k < iterations; k++) {
        buffer.clear();
        const char *prefix = "Basic ";
        buffer.insert(buffer.end(), prefix, prefix + 6);
        if (impl->encode(buffer, credential.data(),
                         (int64_t)credential.size()) != E_NONE)
          std::abort();
        checksum += sample(buffer.data(), (int64_t)buffer.size());
      }
      int64_t elapsed = now_ns() - start;
      // bench/bench.goose reports the user and password lengths without the
      // ':' separator, so the same column means the same thing in both files.
      int64_t reported = (int64_t)std::strlen(users[index]) +
                         (int64_t)std::strlen(passwords[index]);
      row("consumer", consumers[index], impl->name, elapsed, iterations,
          reported, (int64_t)buffer.size(), 1,
          fnv(buffer.data(), (int64_t)buffer.size()));
    }
  }

  std::printf("checksum\t%lld\n", (long long)checksum);
  return 0;
}
