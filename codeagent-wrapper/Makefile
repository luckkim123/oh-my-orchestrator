GO ?= go
# `git describe` fails -- not "returns something odd", fails -- when the build
# happens outside a git checkout, and a build from the PLUGIN CACHE is exactly
# that. The old fallback stamped the literal "dev", which is a version string
# no drift check can compare against; a session on 2026-09-01 rebuilt the wrapper
# from the cache to fix a stale binary and got a binary that could no longer say
# whether it was stale. Fall back to what the plugin manifest declares instead.
# The path is NOT interpolated into the Python source: a directory containing a
# single quote (a legal path, and plugin caches are not always tame) closes the
# string literal, the command fails, and the fallback silently becomes `dev`
# again -- the very state this exists to prevent (codex, 2026-09-01). Python
# derives it from its own cwd instead, which make has already set here.
FALLBACK_VERSION := $(shell python3 -c "import json,pathlib;print(json.loads((pathlib.Path.cwd().parent/'.claude-plugin'/'plugin.json').read_text())['version'])" 2>/dev/null || echo dev)
VERSION := $(shell git describe --tags --always --dirty 2>/dev/null || echo $(FALLBACK_VERSION))
LDFLAGS := -ldflags "-X codeagent-wrapper/internal/app.version=$(VERSION)"

TOOLS_BIN := $(CURDIR)/bin
TOOLCHAIN ?= go1.22.0
GOLANGCI_LINT_VERSION := v1.56.2
STATICCHECK_VERSION := v0.4.7

GOLANGCI_LINT := $(TOOLS_BIN)/golangci-lint
STATICCHECK := $(TOOLS_BIN)/staticcheck

.PHONY: build test lint clean install

build:
	$(GO) build $(LDFLAGS) -o codeagent-wrapper ./cmd/codeagent-wrapper

test:
	$(GO) test ./...

$(GOLANGCI_LINT):
	@mkdir -p $(TOOLS_BIN)
	GOTOOLCHAIN=$(TOOLCHAIN) GOBIN=$(TOOLS_BIN) $(GO) install github.com/golangci/golangci-lint/cmd/golangci-lint@$(GOLANGCI_LINT_VERSION)

$(STATICCHECK):
	@mkdir -p $(TOOLS_BIN)
	GOTOOLCHAIN=$(TOOLCHAIN) GOBIN=$(TOOLS_BIN) $(GO) install honnef.co/go/tools/cmd/staticcheck@$(STATICCHECK_VERSION)

lint: $(GOLANGCI_LINT) $(STATICCHECK)
	GOTOOLCHAIN=$(TOOLCHAIN) $(GOLANGCI_LINT) run ./...
	GOTOOLCHAIN=$(TOOLCHAIN) $(STATICCHECK) ./...

clean:
	@python3 -c 'import glob, os; paths=["codeagent","codeagent.exe","codeagent-wrapper","codeagent-wrapper.exe","coverage.out","cover.out","coverage.html"]; paths += glob.glob("coverage*.out") + glob.glob("cover_*.out") + glob.glob("*.test"); [os.remove(p) for p in paths if os.path.exists(p)]'

install:
	$(GO) install $(LDFLAGS) ./cmd/codeagent-wrapper
