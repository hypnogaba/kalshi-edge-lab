#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────
# kalshi-edge-lab: one-time server bootstrap.
#
# Run this once on a fresh Linux host, from the repo root:
#   bash deploy/setup.sh
#
# Safe to re-run any time (idempotent) — it will not overwrite an existing
# .env, and re-running just re-checks/re-installs what's missing.
# ────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "========================================"
echo "  kalshi-edge-lab: server setup"
echo "  repo: $REPO_ROOT"
echo "========================================"

# 1. uv (Python package/venv manager) ------------------------------------
echo
echo "[1/5] Checking for uv..."
if command -v uv >/dev/null 2>&1; then
    echo "      uv already installed: $(command -v uv) ($(uv --version))"
else
    echo "      uv not found — installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # The installer puts uv in ~/.local/bin, which may not be on PATH yet
    # in this shell session.
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv >/dev/null 2>&1; then
        echo "      uv installed: $(command -v uv) ($(uv --version))"
        echo "      NOTE: add this to your shell profile (~/.bashrc or ~/.profile) so"
        echo "            uv is on PATH in new sessions:"
        echo "              export PATH=\"\$HOME/.local/bin:\$PATH\""
    else
        echo "      ERROR: uv installed but not found on PATH at ~/.local/bin/uv."
        echo "             Add ~/.local/bin to PATH and re-run this script."
        exit 1
    fi
fi

# 2. Python deps ----------------------------------------------------------
echo
echo "[2/5] Installing Python dependencies (uv sync)..."
uv sync

# 3. Directories ------------------------------------------------------------
echo
echo "[3/5] Creating data/ and secrets/ directories..."
mkdir -p data secrets
chmod 700 secrets

# 4. .env -------------------------------------------------------------------
echo
echo "[4/5] Checking .env..."
if [ -f .env ]; then
    echo "      .env already exists — leaving it alone."
else
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "      Created .env from .env.example."
    else
        echo "      WARNING: .env.example not found — skipping .env creation."
    fi
    echo
    echo "      ACTION NEEDED before you can run the race for real:"
    echo "        1. Edit .env and set KALSHI_PROD_KEY_ID to your Kalshi PROD"
    echo "           (read-only) API key ID."
    echo "        2. Put the matching PROD private key file at:"
    echo "             secrets/kalshi_prod_key.pem"
    echo "      (Never commit .env or secrets/ — both are gitignored.)"
fi

# 5. Smoke test -------------------------------------------------------------
echo
echo "[5/5] Running offline self-check (no feed/keys needed)..."
if uv run python -m scripts.run_race --selfcheck; then
    echo
    echo "SELFCHECK: PASS — wiring (matching, stats, report rendering) is good."
else
    echo
    echo "SELFCHECK: FAIL — something in the pipeline is broken. See output above."
    exit 1
fi

echo
echo "========================================"
echo "  Setup complete."
echo "========================================"
echo
echo "Next steps:"
echo "  1. If you haven't already: edit .env (KALSHI_PROD_KEY_ID) and drop the"
echo "     private key at secrets/kalshi_prod_key.pem."
echo "  2. Make sure this host is connected to DoubleZero (see"
echo "     https://docs.malbeclabs.com/setup) and that its receiving IP has"
echo "     an access pass — without both, there is no real DZ feed to race"
echo "     against."
echo "  3. Find the Kalshi feed's multicast group:"
echo "       doublezero multicast group list"
echo "  4. Run the race:"
echo "       MARKET=<ticker> GROUP=<group> IFACE=<iface> bash deploy/run_race.sh"
echo
