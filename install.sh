#!/usr/bin/env bash
# codeagent-wrapper installer.
#
# Until 0.21.6 this script PRINTED two commands and ran neither. The version
# drift it existed to prevent recurred three times, the last on 2026-09-01 when
# a session found v0.20.0 answering on PATH while the plugin cache held 0.21.6.
# An installer that instructs is a README; this one installs.
#
# The real work lives in bin/omo-init so that the seed/loader/census path and
# this path cannot drift apart.
set -euo pipefail
exec python3 "$(dirname "$0")/bin/omo-init" --wrapper-only "$@"
