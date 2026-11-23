#!/usr/bin/env bash
# A safe Codespaces bootstrap. This never downloads the commercial game.
# Usage: bash web/tools/gt4-codespace.sh check|prepare|build|run [--data GAME_DIR] [--port 8080]
set -eo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
MODE="${1:-check}"
if [ "$#" -gt 0 ]; then shift; fi
GAME="$ROOT/.nfsu2-local/game"
if [ -n "$NFSU2_DATA" ]; then GAME="$NFSU2_DATA"; fi
PORT=8080
SHA256=f9dd86c054878ce6276beb07c1fd61874f7a1e4bf1f241b084c65b73e24168a7
SIZE=4800512

usage() {
cat <<'EOF'
NFSU2 GT4 Web — Codespaces (Linux x86_64, no local Windows admin)
  bash web/tools/gt4-codespace.sh check [--data GAME_DIR]
  bash web/tools/gt4-codespace.sh prepare  # install free build tools, no game needed
  bash web/tools/gt4-codespace.sh build [--data GAME_DIR]
  bash web/tools/gt4-codespace.sh run   [--data GAME_DIR] [--port 8080]
Keep your legally obtained Underground 2 PC v1.2 NA installation in
.nfsu2-local/game/ (ignored by Git), or specify --data.
The helper only downloads public build tools, never copyrighted game assets.
When running in Codespaces, forward port 8080 from the Ports panel.
EOF
}
if [ "$MODE" = --help ] || [ "$MODE" = -h ]; then usage; exit 0; fi
case "$MODE" in check|prepare|build|run) ;; *) usage >&2; exit 2 ;; esac
while [ "$#" -gt 0 ]; do
  case "$1" in
    --data) if [ "$#" -lt 2 ]; then echo "Missing --data value" >&2; exit 2; fi; GAME="$2"; shift 2 ;;
    --port) if [ "$#" -lt 2 ]; then echo "Missing --port value" >&2; exit 2; fi; PORT="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || ! (( PORT >= 1 && PORT <= 65535 )); then
  echo "Invalid port: $PORT" >&2; exit 2
fi
echo "[gt4] mode=$MODE; game=$GAME"
error=0
need() {
  if ! command -v "$1" >/dev/null 2>&1; then echo "[gt4] Missing tool: $1"; error=1
  else echo "[gt4] Tool available: $1"; fi
}
for cmd in python3 node npm rustc cargo sha256sum; do need "$cmd"; done
if command -v node >/dev/null 2>&1; then
  major="$(node -p 'process.versions.node.split(".")[0]')"
  if (( major < 20 )); then echo "[gt4] Node 20+ required, found $major"; error=1; fi
fi
if [ "$MODE" != prepare ] && [ ! -f "$GAME/SPEED2.EXE" ]; then
  echo "[gt4] Missing game executable: $GAME/SPEED2.EXE"
  echo "[gt4] Supply your licensed original game files outside tracked directories."
  error=1
elif [ "$MODE" != prepare ]; then
  actual_size="$(wc -c < "$GAME/SPEED2.EXE" | tr -d ' ')"
  actual_hash="$(sha256sum "$GAME/SPEED2.EXE" | cut -d' ' -f1)"
  if [ "$actual_size" != "$SIZE" ] || [ "$actual_hash" != "$SHA256" ]; then
    echo "[gt4] Unsupported SPEED2.EXE: $actual_size bytes, SHA-256 $actual_hash"
    echo "[gt4] Required: NA v1.2, $SIZE bytes, SHA-256 $SHA256"
    error=1
  else echo "[gt4] Game executable checksum matches NA v1.2."; fi
fi
if (( error )); then echo "[gt4] Preflight incomplete; no build started."; exit 1; fi
if [ "$MODE" = check ]; then echo "[gt4] Preflight passed."; exit 0; fi
if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
  echo "[gt4] Automated wasi-sdk bootstrap supports Linux x86_64 only." >&2; exit 2
fi
if ! compgen -G "$ROOT/deps/wasi-sdk-34*/bin/clang" >/dev/null; then
  need curl; need tar; if (( error )); then exit 1; fi
  mkdir -p deps
  echo "[gt4] Downloading public wasi-sdk 34 into gitignored deps/."
  tmp="$(mktemp "$ROOT/deps/.wasi-sdk.XXXXXX")"
  trap 'rm -f "$tmp"' EXIT
  curl -fL --retry 3 --silent --show-error \
    "https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-34/wasi-sdk-34.0-x86_64-linux.tar.gz" -o "$tmp"
  tar -xzf "$tmp" -C deps
  rm -f "$tmp"
  trap - EXIT
fi
if ! compgen -G "$ROOT/deps/wasi-sdk-34*/bin/clang" >/dev/null; then
  echo "[gt4] wasi-sdk missing or incomplete." >&2; exit 1
fi
echo "[gt4] Preparing build dependencies."
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
(cd web && npm ci --no-audit --no-fund)
if [ "$MODE" = prepare ]; then
  echo "[gt4] Checking and building the open-source browser interface (no game needed)."
  (cd web && npm run check && npm run build)
  echo "[gt4] Ready for your compatible game files. To verify: bash web/tools/gt4-codespace.sh check"
  exit 0
fi
echo "[gt4] Generating and compiling WASM from the owner's compatible executable."
web/gen.sh "$GAME/SPEED2.EXE"
if [ -z "$J" ]; then export J=2; fi
web/build.sh
(cd web && npm run build)
if [ "$MODE" = build ]; then echo "[gt4] Build complete."; exit 0; fi
echo "[gt4] Starting web server on port $PORT (Codespaces: forward this port)."
exec web/start.sh --data "$GAME" --http-port "$PORT"
