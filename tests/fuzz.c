// SPDX-License-Identifier: Apache-2.0
// libFuzzer driver for tests/fuzz.goose. The fuzzer calls the exported Goose
// entry point, so the code under test is the real `b64::encode` and
// `b64::decode`, compiled by the pinned compiler, with the Goose runtime
// inlined. Nothing here reimplements the codec.
//
// Two failure paths are wired deliberately:
//
//   * Goose aborts on a failed assertion with `_Exit`. The build remaps `_Exit`
//     to `goose_fuzz_exit`, which calls `abort()` for a non-zero status so
//     libFuzzer retains the exact triggering input. `GOOSE_FUZZ_SELF_TEST`
//     builds a binary that trips that path on a known input, and the runner
//     checks the saved artifact byte for byte before any campaign.
//   * `NEGATIVE_CONTROL` builds a binary with a deliberate one-byte overread,
//     so the runner can prove ASan is instrumented in this build rather than
//     assume it.
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "base64-fuzz.h"

// Remapped only in the generated Goose C, never in this file or the runtime.
_Noreturn void goose_fuzz_exit(int status) {
    if (status != 0) abort();
    _Exit(status);
}

int LLVMFuzzerInitialize(int *argc, char ***argv) {
    goose_init(*argc, *argv);
    atexit(goose_exit);
    return 0;
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size > INT64_MAX) return 0;
#ifdef NEGATIVE_CONTROL
    // Deliberate defect: one byte past the input. ASan must report it.
    volatile uint8_t overread = data[size];
    (void)overread;
#endif
#ifdef GOOSE_FUZZ_SELF_TEST
    static const uint8_t probe[] = "libFuzzer Goose assertion bridge probe";
    if (size == sizeof(probe) - 1 && memcmp(data, probe, size) == 0)
        fuzz_assertion_probe(0);
#endif
    (void)fuzz_base64((sl_u8){(uint8_t *)data, (int64_t)size});
    return 0;
}
