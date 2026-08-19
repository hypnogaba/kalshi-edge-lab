"""Render a latency-race PNG report: histogram + timeline, dark-friendly.

Headless-safe: forces the Agg backend before importing pyplot, so this
module is importable and usable with no display (server, CI, cron).
"""
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

_BG = "#1e1e2e"
_FG = "#cdd6f4"
_ACCENT = "#89b4fa"
_ZERO_LINE = "#f38ba8"


def render_report(deltas_ns: list[int], out_png: str, title: str = "Latency race") -> None:
    deltas_ms = [d / 1e6 for d in deltas_ns]

    fig, (ax_hist, ax_time) = plt.subplots(
        2, 1, figsize=(10, 8), facecolor=_BG, gridspec_kw={"height_ratios": [1, 1]},
    )
    fig.suptitle(title, color=_FG, fontsize=14)

    for ax in (ax_hist, ax_time):
        ax.set_facecolor(_BG)
        ax.tick_params(colors=_FG)
        for spine in ax.spines.values():
            spine.set_color(_FG)
        ax.xaxis.label.set_color(_FG)
        ax.yaxis.label.set_color(_FG)
        ax.title.set_color(_FG)

    ax_hist.set_title("Delta histogram")
    ax_hist.set_xlabel("delta (ms), positive = B arrived later")
    ax_hist.set_ylabel("count")
    if deltas_ms:
        ax_hist.hist(deltas_ms, bins=30, color=_ACCENT, edgecolor=_BG)
    ax_hist.axvline(0, color=_ZERO_LINE, linewidth=1, linestyle="--")

    ax_time.set_title("Delta timeline")
    ax_time.set_xlabel("match index")
    ax_time.set_ylabel("delta (ms)")
    if deltas_ms:
        ax_time.scatter(range(len(deltas_ms)), deltas_ms, color=_ACCENT, s=12)
    ax_time.axhline(0, color=_ZERO_LINE, linewidth=1, linestyle="--")

    fig.tight_layout()
    fig.savefig(out_png, facecolor=_BG)
    plt.close(fig)
