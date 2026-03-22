#!/usr/bin/env python3
"""
Claude Code Usage Tracker — SwiftBar plugin
Parses local JSONL logs from ~/.claude/projects/ to display token usage.
100% offline — no network calls, no data leaves your machine.

NOTE: Only tracks Claude Code usage. Web (claude.ai) usage is not captured
but counts toward the same limits. Percentages may undercount if you also
use the web interface.
"""

import json
import os
import glob
from datetime import datetime, timezone, timedelta
from collections import defaultdict

CLAUDE_DIR = os.path.expanduser("~/.claude/projects")
CONFIG_PATH = os.path.expanduser("~/.claude/usage-tracker-config.json")
WINDOW_5H = timedelta(hours=5)
WINDOW_7D = timedelta(days=7)

# Calibrated defaults (output tokens) — derived from actual usage screenshots.
# Adjust in ~/.claude/usage-tracker-config.json as you learn your exact limits.
# These are for Max 5x ($100/mo). March 2026 promo may temporarily double them.
DEFAULT_CONFIG = {
    "limits": {
        "5h": {
            "total": 2_000_000,
        },
        "7d": {
            "all_models": 13_000_000,
            "sonnet": 7_000_000,
        },
    }
}

MODEL_NAMES = {
    "opus": "Opus",
    "sonnet": "Sonnet",
    "haiku": "Haiku",
}

BAR_WIDTH = 20
FILL_CHAR = "█"
EMPTY_CHAR = "░"


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                user_cfg = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg["limits"] = DEFAULT_CONFIG["limits"].copy()
            if "limits" in user_cfg:
                for window in ("5h", "7d"):
                    if window in user_cfg["limits"]:
                        cfg["limits"][window] = {
                            **DEFAULT_CONFIG["limits"].get(window, {}),
                            **user_cfg["limits"][window],
                        }
            return cfg
        except (json.JSONDecodeError, KeyError):
            pass
    return DEFAULT_CONFIG


def classify_model(model_id):
    if not model_id:
        return "unknown"
    model_lower = model_id.lower()
    for key in MODEL_NAMES:
        if key in model_lower:
            return key
    return "other"


def friendly_model(key):
    return MODEL_NAMES.get(key, key.title())


def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def progress_bar(current, limit, width=BAR_WIDTH):
    if limit <= 0:
        return FILL_CHAR * width, 100
    pct = min(current / limit, 1.0)
    filled = int(pct * width)
    bar = FILL_CHAR * filled + EMPTY_CHAR * (width - filled)
    return bar, pct * 100


def bar_color(pct):
    if pct >= 90:
        return "#EF4444"
    if pct >= 70:
        return "#F59E0B"
    if pct >= 50:
        return "#FBBF24"
    return "#10B981"


def parse_logs():
    now = datetime.now(timezone.utc)
    cutoff_5h = now - WINDOW_5H
    cutoff_7d = now - WINDOW_7D

    usage_5h = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0})
    usage_7d = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0})
    msg_count_5h = 0
    msg_count_7d = 0

    jsonl_files = glob.glob(os.path.join(CLAUDE_DIR, "**", "*.jsonl"), recursive=True)

    for filepath in jsonl_files:
        try:
            mtime = os.path.getmtime(filepath)
            if datetime.fromtimestamp(mtime, tz=timezone.utc) < cutoff_7d:
                continue
        except OSError:
            continue

        try:
            with open(filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = entry.get("message", {})
                    if not isinstance(msg, dict):
                        continue
                    usage = msg.get("usage")
                    if not usage:
                        continue
                    if msg.get("role") != "assistant":
                        continue

                    ts_str = entry.get("timestamp")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except (ValueError, AttributeError):
                        continue

                    if ts < cutoff_7d:
                        continue

                    model = classify_model(msg.get("model", ""))
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    cache_read = usage.get("cache_read_input_tokens", 0)
                    cache_create = usage.get("cache_creation_input_tokens", 0)

                    usage_7d[model]["input"] += input_tokens
                    usage_7d[model]["output"] += output_tokens
                    usage_7d[model]["cache_read"] += cache_read
                    usage_7d[model]["cache_create"] += cache_create
                    msg_count_7d += 1

                    if ts >= cutoff_5h:
                        usage_5h[model]["input"] += input_tokens
                        usage_5h[model]["output"] += output_tokens
                        usage_5h[model]["cache_read"] += cache_read
                        usage_5h[model]["cache_create"] += cache_create
                        msg_count_5h += 1

        except (OSError, PermissionError):
            continue

    return {
        "5h": usage_5h,
        "7d": usage_7d,
        "messages_5h": msg_count_5h,
        "messages_7d": msg_count_7d,
    }


def total_output(usage_dict):
    return sum(v["output"] for v in usage_dict.values())


def model_output(usage_dict, model):
    return usage_dict.get(model, {}).get("output", 0)


def total_input(usage_dict):
    return sum(v["input"] for v in usage_dict.values())


def render():
    config = load_config()
    data = parse_logs()
    limits_5h = config["limits"]["5h"]
    limits_7d = config["limits"]["7d"]

    # Calculate percentages
    total_out_5h = total_output(data["5h"])
    total_out_7d = total_output(data["7d"])
    sonnet_out_7d = model_output(data["7d"], "sonnet")

    limit_5h = limits_5h.get("total", 1)
    limit_7d_all = limits_7d.get("all_models", 1)
    limit_7d_sonnet = limits_7d.get("sonnet", 1)

    pct_5h = min(total_out_5h / limit_5h * 100, 100) if limit_5h > 0 else 0
    pct_7d_all = min(total_out_7d / limit_7d_all * 100, 100) if limit_7d_all > 0 else 0
    pct_7d_sonnet = min(sonnet_out_7d / limit_7d_sonnet * 100, 100) if limit_7d_sonnet > 0 else 0

    # Menu bar title — show highest percentage (most constrained)
    max_pct = max(pct_5h, pct_7d_all, pct_7d_sonnet)
    tc = bar_color(max_pct)

    if total_out_5h == 0 and total_out_7d == 0:
        print("C: idle | sfimage=brain.head.profile")
    else:
        mini_bar, _ = progress_bar(max_pct, 100, width=8)
        print(f"C: {mini_bar} {max_pct:.0f}% | sfimage=brain.head.profile color={tc}")

    print("---")

    # === Current Session (5-hour window) ===
    bar_5h, _ = progress_bar(total_out_5h, limit_5h)
    bc_5h = bar_color(pct_5h)
    print(f"Current Session — {pct_5h:.0f}% | size=14 color=#7C3AED")
    print(f"--{bar_5h} {pct_5h:.0f}% | font=Menlo size=12 color={bc_5h}")
    print(f"--{fmt_tokens(total_out_5h)} / {fmt_tokens(limit_5h)} output tokens | font=Menlo size=12")
    print(f"--Messages: {data['messages_5h']} | font=Menlo size=12")
    print("-----")
    # Per-model breakdown (info only, not separate limits)
    print("--By Model | size=12")
    for model_key in ("opus", "sonnet", "haiku"):
        out = model_output(data["5h"], model_key)
        inp = data["5h"].get(model_key, {}).get("input", 0)
        if out > 0 or inp > 0:
            name = friendly_model(model_key)
            share = (out / total_out_5h * 100) if total_out_5h > 0 else 0
            print(f"----{name}: {fmt_tokens(out)} out, {fmt_tokens(inp)} in ({share:.0f}%) | font=Menlo size=11")

    print("---")

    # === Weekly Limits ===
    print(f"Weekly Limits | size=14 color=#2563EB")

    # All models
    bar_7d, _ = progress_bar(total_out_7d, limit_7d_all)
    bc_7d = bar_color(pct_7d_all)
    print(f"--All Models — {pct_7d_all:.0f}% | size=13")
    print(f"----{bar_7d} {pct_7d_all:.0f}% | font=Menlo size=12 color={bc_7d}")
    print(f"----{fmt_tokens(total_out_7d)} / {fmt_tokens(limit_7d_all)} output tokens | font=Menlo size=12")
    print(f"----Messages: {data['messages_7d']} | font=Menlo size=12")

    # Sonnet only
    bar_sonnet, _ = progress_bar(sonnet_out_7d, limit_7d_sonnet)
    bc_sonnet = bar_color(pct_7d_sonnet)
    print(f"--Sonnet Only — {pct_7d_sonnet:.0f}% | size=13")
    print(f"----{bar_sonnet} {pct_7d_sonnet:.0f}% | font=Menlo size=12 color={bc_sonnet}")
    print(f"----{fmt_tokens(sonnet_out_7d)} / {fmt_tokens(limit_7d_sonnet)} output tokens | font=Menlo size=12")

    print("-----")
    # Per-model breakdown (info only)
    print("--By Model | size=12")
    for model_key in ("opus", "sonnet", "haiku"):
        out = model_output(data["7d"], model_key)
        inp = data["7d"].get(model_key, {}).get("input", 0)
        if out > 0 or inp > 0:
            name = friendly_model(model_key)
            share = (out / total_out_7d * 100) if total_out_7d > 0 else 0
            print(f"----{name}: {fmt_tokens(out)} out, {fmt_tokens(inp)} in ({share:.0f}%) | font=Menlo size=11")

    print("---")

    # Cache summary
    cache_r_5h = sum(v["cache_read"] for v in data["5h"].values())
    cache_c_5h = sum(v["cache_create"] for v in data["5h"].values())
    print(f"Cache (5h): {fmt_tokens(cache_r_5h)} read, {fmt_tokens(cache_c_5h)} write | size=11 color=gray")

    print("---")

    # Caveat
    print("Claude Code only — web usage not tracked | size=10 color=#F59E0B")

    print("---")

    # Config
    print(f"Settings | size=12")
    print(f"--Config: {CONFIG_PATH} | size=10 color=gray")
    print(f"--Edit config | size=11 bash=open param1={CONFIG_PATH} terminal=false")
    if not os.path.exists(CONFIG_PATH):
        print(f"--Create default config | size=11 bash=python3 param1=-c param2=import\\ json;open('{CONFIG_PATH}','w').write(json.dumps({json.dumps(DEFAULT_CONFIG)},indent=2)) terminal=false refresh=true")

    print("---")
    print("Refresh | refresh=true")
    now_str = datetime.now().strftime("%H:%M")
    print(f"Updated {now_str} | size=10 color=gray")


if __name__ == "__main__":
    render()
