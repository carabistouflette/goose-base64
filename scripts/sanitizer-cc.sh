#!/usr/bin/env bash
set -euo pipefail
exec "${SANITIZER_CC:-gcc}" "$@" -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie
