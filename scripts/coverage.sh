#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
coverage_file="${1:-${project_root}/coverage.out}"

cd "${project_root}"
go test -coverpkg=./... -coverprofile="${coverage_file}" ./tests/...
go tool cover -func="${coverage_file}"
