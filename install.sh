#!/bin/bash
# LEGACY SHIM -- the binary download this script used to do was removed in
# 0.20.0. It pulled codeagent-wrapper from the UPSTREAM fork's releases
# (stellarlinkco/myclaude), whose builds lack the agy backend and this fork's
# ledger/guards, and it OVERWROTE a locally built binary while every
# existence check kept passing (skills/omo/references/vendor-ops.md).
#
# Build from source instead -- see README.md "Install":
#   cd codeagent-wrapper && make build && make install
#   ln -sf "$(go env GOPATH)/bin/codeagent-wrapper" ~/.local/bin/codeagent-wrapper
set -e
echo "install.sh no longer downloads binaries (0.20.0)." >&2
echo "Build from source: cd codeagent-wrapper && make build && make install" >&2
echo "Then symlink: ln -sf \"\$(go env GOPATH)/bin/codeagent-wrapper\" ~/.local/bin/codeagent-wrapper" >&2
exit 1
