"""Main loop wiring: poll real Kalshi trades + Binance spot -> naive v0 signal -> guardrails ->
Kalshi DEMO order -> decision log. DEMO only. Not unit-tested here — validated live via a
signal-only dry run (kill switch engaged, zero orders placed)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import time
import uuid
from dataclasses import replace

import httpx

from bot.config import BotConfig
from bot.decision_log import DecisionLog
from bot.guardrails import GuardrailBreach, Guardrails
from bot.order_manager import OrderManager
from bot.signal import Decision, SignalConfig, decide
from common.clock import now_ns
from common.config import kalshi_demo
from reference.binance_ws import BinanceRef
from sources.kalshi_rest.client import KalshiRestClient
from sources.kalshi_rest.selector import nearest_markets, parse_strike

logger = logging.getLogger("bot.run")

_THRESHOLD_SUFFIX = re.compile(r"-T\d+(?:\.\d+)?$")
_BINANCE_SPOT_URL = "https://api.binance.com/api/v3/ticker/price"


def is_threshold_ticker(ticker: str) -> bool:
    """Threshold markets ('BTC >= strike?') end in -T<strike>; bucket markets (-B<strike>) are HOLD-only."""
    return bool(_THRESHOLD_SUFFIX.search(ticker))


def fetch_one_shot_spot() -> float | None:
    """One-shot Binance REST spot, used to seed market selection if the WS mid isn't ready yet."""
    try:
        r = httpx.get(_BINANCE_SPOT_URL, params={"symbol": "BTCUSDT"}, timeout=5.0)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception:  # noqa: BLE001 - fall back to None, caller handles missing spot
        return None


def build_watchlist(rest: KalshiRestClient, series: str, near: int, spot: float | None) -> list[str]:
    """Near-money threshold BTC markets for `series`, nearest `near` by strike distance to `spot`."""
    markets = rest.markets(series)
    tickers = [m["ticker"] for m in markets if m.get("ticker")]
    threshold_tickers = [t for t in tickers if is_threshold_ticker(t) and parse_strike(t) is not None]
    if not threshold_tickers or spot is None:
        return []
    return nearest_markets(threshold_tickers, spot=spot, n=near)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Kalshi BTC threshold demo bot (Phase 2, DEMO only)")
    p.add_argument("--minutes", type=float, default=None, help="stop after this many minutes")
    p.add_argument("--kill-switch", type=str, default=None, help="path to kill-switch file")
    p.add_argument("--decision-log", type=str, default=None, help="path to decision-log JSONL")
    p.add_argument("--series", type=str, default=None, help="Kalshi series ticker")
    p.add_argument("--near", type=int, default=None, help="number of near-money markets to watch")
    p.add_argument("--interval", type=float, default=None, help="poll interval in seconds")
    return p.parse_args(argv)


def _config_from_args(args: argparse.Namespace) -> BotConfig:
    cfg = BotConfig.from_env()
    overrides: dict = {}
    if args.kill_switch is not None:
        overrides["kill_switch_path"] = args.kill_switch
    if args.decision_log is not None:
        overrides["decision_log_path"] = args.decision_log
    if args.series is not None:
        overrides["series"] = args.series
    if args.near is not None:
        overrides["near"] = args.near
    if args.interval is not None:
        overrides["poll_interval_s"] = args.interval
    return replace(cfg, **overrides) if overrides else cfg


async def run(cfg: BotConfig, minutes: float | None) -> None:
    binance = BinanceRef()
    binance_task = asyncio.create_task(binance.run())

    kalshi_cfg = kalshi_demo()
    rest = KalshiRestClient()
    order_mgr = OrderManager(kalshi_cfg.key_id, kalshi_cfg.private_key_path, kalshi_cfg.api_base)
    guardrails = Guardrails(
        cfg.max_position, cfg.max_orders_per_min, cfg.max_daily_loss_cents, cfg.kill_switch_path
    )
    logger.warning(
        "daily-loss guardrail inert in v0 (paper PnL not tracked); "
        "position, rate-limit, and kill-switch guardrails are active"
    )
    log = DecisionLog(cfg.decision_log_path)
    sig_cfg = SignalConfig(cfg.entry_dollars, cfg.max_yes_cents, cfg.min_yes_cents)

    position = 0
    # v0: paper PnL not yet tracked (needs fills); daily-loss ceiling is a placeholder until then
    daily_pnl_cents = 0

    try:
        seed_spot = binance.mid if binance.mid is not None else fetch_one_shot_spot()
        watchlist = build_watchlist(rest, cfg.series, cfg.near, seed_spot)
        print(f"[bot] series={cfg.series} watching {len(watchlist)} threshold markets: {watchlist}")

        deadline = time.monotonic() + minutes * 60 if minutes is not None else None
        while deadline is None or time.monotonic() < deadline:
            for ticker in watchlist:
                try:
                    trades = rest.trades(ticker, limit=1)
                    kalshi_yes_cents = (
                        round(float(trades[0]["yes_price_dollars"]) * 100) if trades else None
                    )
                    spot = binance.mid
                    strike = parse_strike(ticker)

                    if spot is None or kalshi_yes_cents is None or strike is None:
                        log.record(
                            now_ns(), ticker, kalshi_yes_cents, spot, Decision.HOLD.value,
                            "hold", {"reason": "missing spot or trade data"},
                        )
                        continue

                    sig = decide(strike, True, kalshi_yes_cents, spot, sig_cfg)

                    if sig == Decision.HOLD:
                        log.record(now_ns(), ticker, kalshi_yes_cents, spot, sig.value, "hold", None)
                        continue

                    try:
                        guardrails.check(position, cfg.order_count, daily_pnl_cents, now_s=time.monotonic())
                    except GuardrailBreach as breach:
                        log.record(
                            now_ns(), ticker, kalshi_yes_cents, spot, sig.value,
                            "blocked", {"reason": str(breach)},
                        )
                        continue

                    coid = str(uuid.uuid4())
                    order_id = order_mgr.place(
                        ticker=ticker, buy_yes=(sig == Decision.BUY_YES),
                        count=cfg.order_count, price_cents=cfg.order_price_cents, coid=coid,
                    )
                    position += cfg.order_count
                    log.record(
                        now_ns(), ticker, kalshi_yes_cents, spot, sig.value,
                        "placed", {"order_id": order_id, "client_order_id": coid},
                    )
                except Exception as e:  # noqa: BLE001 - one bad market must not kill the loop
                    print(f"[bot] error polling {ticker}: {e!r}")

            await asyncio.sleep(cfg.poll_interval_s)
    finally:
        binance.stop()
        binance_task.cancel()
        try:
            await binance_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110 - task is being torn down
            pass
        rest.close()
        order_mgr.close()
        log.close()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    cfg = _config_from_args(args)
    asyncio.run(run(cfg, args.minutes))


if __name__ == "__main__":
    main()
