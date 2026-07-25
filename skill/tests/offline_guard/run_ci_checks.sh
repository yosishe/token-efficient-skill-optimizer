#!/usr/bin/env bash
set -uo pipefail

: "${PYTHON_BIN:?PYTHON_BIN must be the absolute setup-python interpreter}"
if [[ "$PYTHON_BIN" != /* || ! -x "$PYTHON_BIN" ]]; then
  printf 'PYTHON_BIN must name an executable absolute path\n' >&2
  exit 1
fi

cd "$GITHUB_WORKSPACE"
mkdir -p "$VERIFICATION_DIR" || exit 1
if [[ "${TESO_HARDENED_SANDBOX:-0}" == "1" ]]; then
  if [[ "$(id -u)" == "0" ]]; then
    printf 'hardened test identity must not be root\n' >&2
    exit 1
  fi
  if command -v sudo >/dev/null && sudo -n true >/dev/null 2>&1; then
    printf 'hardened test identity must not retain passwordless sudo\n' >&2
    exit 1
  fi
  if [[ -r /proc/self/status ]] \
      && ! grep -Eq '^NoNewPrivs:[[:space:]]+1$' /proc/self/status; then
    printf 'hardened test process must set no_new_privs\n' >&2
    exit 1
  fi
  printf 'active\n' > "$VERIFICATION_DIR/hardened-sandbox.status" || exit 1
fi
printf 'active\n' > "$VERIFICATION_DIR/network-namespace.status" || exit 1
overall=0

record_pipeline_status() {
  local name="$1"
  local command_status="$2"
  local tee_status="$3"
  if ! printf 'command=%s\ntee=%s\n' "$command_status" "$tee_status" \
      > "$VERIFICATION_DIR/$name.exit"; then
    overall=1
  fi
  if ((command_status != 0 || tee_status != 0)); then
    overall=1
  fi
}

"$PYTHON_BIN" skill/scripts/run_tests.py \
  2>&1 | tee "$VERIFICATION_DIR/tests.txt"
legacy_pipe=("${PIPESTATUS[@]}")
record_pipeline_status "tests" "${legacy_pipe[0]}" "${legacy_pipe[1]}"

"$PYTHON_BIN" -m unittest discover -s skill/tests -p 'test_v2.py' -v \
  2>&1 | tee "$VERIFICATION_DIR/v2-tests.txt"
v2_pipe=("${PIPESTATUS[@]}")
record_pipeline_status "v2-tests" "${v2_pipe[0]}" "${v2_pipe[1]}"
"$PYTHON_BIN" skill/scripts/parse_unittest.py \
  "$VERIFICATION_DIR/v2-tests.txt" \
  --require-executed-at-least 1 \
  --require-test-manifest skill/tests/v2-test-manifest.json \
  --require-no-skips \
  > "$VERIFICATION_DIR/v2-tests.counts.json"
v2_discovery_status=$?
if ! printf '%s\n' "$v2_discovery_status" \
    > "$VERIFICATION_DIR/v2-discovery.exit"; then
  overall=1
fi
if ((v2_discovery_status != 0)); then
  overall=1
fi

"$PYTHON_BIN" skill/scripts/validate_package.py skill \
  --json "$VERIFICATION_DIR/package.json" \
  2>&1 | tee "$VERIFICATION_DIR/package.txt"
package_pipe=("${PIPESTATUS[@]}")
record_pipeline_status "package" "${package_pipe[0]}" "${package_pipe[1]}"

"$PYTHON_BIN" skill/scripts/render_rules.py \
  2>&1 | tee "$VERIFICATION_DIR/render.txt"
render_pipe=("${PIPESTATUS[@]}")
render_status="${render_pipe[0]}"
record_pipeline_status "render" "$render_status" "${render_pipe[1]}"

git -c safe.directory="$GITHUB_WORKSPACE" status \
  --porcelain --untracked-files=all \
  > "$VERIFICATION_DIR/generated-drift.txt"
git_status=$?
if ! printf '%s\n' "$git_status" > "$VERIFICATION_DIR/git-status.exit"; then
  overall=1
fi
if ((render_status == 0 && git_status == 0)) \
    && [[ ! -s "$VERIFICATION_DIR/generated-drift.txt" ]]; then
  printf 'passed\n' > "$VERIFICATION_DIR/generated-drift.status" || overall=1
else
  printf 'failed\n' > "$VERIFICATION_DIR/generated-drift.status" || true
  overall=1
fi

exit "$overall"
