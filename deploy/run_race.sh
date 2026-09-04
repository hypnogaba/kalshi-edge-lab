#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────
# kalshi-edge-lab: turnkey latency-race runner.
#
# Checks the DoubleZero tunnel is up, shows available multicast groups,
# then runs the race and tells you where the results landed.
#
# Usage (env vars):
#   MARKET=KXBTCPERP GROUP=233.84.178.3 IFACE=doublezero1 bash deploy/run_race.sh
#
# Or with flags:
#   bash deploy/run_race.sh --market KXBTCPERP --group 233.84.178.3 --iface doublezero1
#
# Config (env var or flag), with defaults:
#   MARKET          --market          (required, no default)
#   GROUP           --group           (required, no default)
#   IFACE           --iface           (required, no default)
#   MKTDATA_PORT    --mktdata-port    default 31000
#   REFDATA_PORT    --refdata-port    default 41000
#   MINUTES         --minutes         default 10
# ────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MKTDATA_PORT="${MKTDATA_PORT:-31000}"
REFDATA_PORT="${REFDATA_PORT:-41000}"
MINUTES="${MINUTES:-10}"
MARKET="${MARKET:-}"
GROUP="${GROUP:-}"
IFACE="${IFACE:-}"

# --- parse flags (override env vars if given) ---------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --market) MARKET="$2"; shift 2 ;;
        --group) GROUP="$2"; shift 2 ;;
        --iface) IFACE="$2"; shift 2 ;;
        --mktdata-port) MKTDATA_PORT="$2"; shift 2 ;;
        --refdata-port) REFDATA_PORT="$2"; shift 2 ;;
        --minutes) MINUTES="$2"; shift 2 ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: bash deploy/run_race.sh [--market T] [--group IP] [--iface NAME] [--mktdata-port N] [--refdata-port N] [--minutes N]"
            exit 1
            ;;
    esac
done

echo "========================================"
echo "  kalshi-edge-lab: run race"
echo "========================================"

# 1. Check the DoubleZero tunnel is up -----------------------------------
echo
echo "[1/5] Checking DoubleZero tunnel (doublezero1)..."
if ip a s doublezero1 >/dev/null 2>&1; then
    echo "      OK — doublezero1 interface found."
else
    echo "      ERROR: DoubleZero tunnel not found (no 'doublezero1' interface)."
    echo "             Connect this host to DoubleZero first (see"
    echo "             https://docs.malbeclabs.com/setup) and make sure your"
    echo "             receiving IP has an access pass."
    exit 1
fi

# 2. Show available multicast groups (best-effort) -----------------------
echo
echo "[2/5] Available DoubleZero multicast groups..."
if command -v doublezero >/dev/null 2>&1; then
    doublezero multicast group list || echo "      (command failed — continuing anyway)"
else
    echo "      NOTE: 'doublezero' CLI not found on PATH — skipping group listing."
    echo "            You'll need to already know the Kalshi feed's GROUP address."
fi

# 3. Require MARKET, GROUP, IFACE -----------------------------------------
echo
echo "[3/5] Checking required config..."
missing=()
[ -z "$MARKET" ] && missing+=("MARKET (--market)")
[ -z "$GROUP" ] && missing+=("GROUP (--group)")
[ -z "$IFACE" ] && missing+=("IFACE (--iface)")

if [ ${#missing[@]} -gt 0 ]; then
    echo "      ERROR: missing required config:"
    for m in "${missing[@]}"; do
        echo "        - $m"
    done
    echo
    echo "      Example:"
    echo "        MARKET=KXBTCPERP GROUP=233.84.178.3 IFACE=doublezero1 bash deploy/run_race.sh"
    exit 1
fi
echo "      MARKET=$MARKET  GROUP=$GROUP  IFACE=$IFACE"
echo "      MKTDATA_PORT=$MKTDATA_PORT  REFDATA_PORT=$REFDATA_PORT  MINUTES=$MINUTES"

# 4. Run the race -----------------------------------------------------------
echo
echo "[4/5] Running the race for $MINUTES minute(s)..."
uv run python -m scripts.run_race \
    --minutes "$MINUTES" \
    --market "$MARKET" \
    --group "$GROUP" \
    --mktdata-port "$MKTDATA_PORT" \
    --refdata-port "$REFDATA_PORT" \
    --link "$IFACE" \
    --out-dir data/race

# 5. Report location ----------------------------------------------------------
echo
echo "[5/5] Done."
echo "      Chart: $REPO_ROOT/data/race/race.png"
echo "      Stats were printed above (p50/p90/p99 etc.)."
