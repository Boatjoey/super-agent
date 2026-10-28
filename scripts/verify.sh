#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${project_root}"

# The strict sandbox is the Linux default, and these are its declared system
# dependencies. Fail here instead of letting the sandbox tests skip silently.
if [[ "$(uname -s)" == "Linux" ]]; then
    for tool in bwrap prlimit; do
        if ! command -v "${tool}" >/dev/null 2>&1; then
            printf 'missing Linux sandbox dependency: %s (install bubblewrap or util-linux)\n' "${tool}" >&2
            exit 1
        fi
    done
fi

# The four gates: formatting, linting, strict typing, and behaviour.
npm run check:web
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest

# Concurrency stress: `python -X dev` enables asyncio debug mode and turns
# un-awaited coroutines and unclosed resources into visible errors. It is the
# project's closest approximation of a race detector; see docs/development.md.
concurrency_paths=""
for candidate in tests/runtime tests/tools; do
    if compgen -G "${candidate}/test_*.py" >/dev/null; then
        concurrency_paths="${concurrency_paths} ${candidate}"
    fi
done
if [[ -z "${concurrency_paths}" ]]; then
    printf 'no concurrency test directories found under tests/\n' >&2
    exit 1
fi
# shellcheck disable=SC2086 # the list is built as a deliberately split string
uv run python -X dev -m pytest ${concurrency_paths}

./scripts/coverage.sh
