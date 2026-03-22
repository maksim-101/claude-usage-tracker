#!/usr/bin/env python3
"""
Claude Code Usage Tracker — SwiftBar plugin
Parses local JSONL logs from ~/.claude/projects/ to display token usage.
100% offline — no network calls, no data leaves your machine.
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

# Default limits (output tokens) — based on Max 5x community estimates.
# Adjust in ~/.claude/usage-tracker-config.json once you learn your actual limits.
DEFAULT_CONFIG = {
    "limits": {
        "5h": {
            "opus": 800_000,
            "sonnet": 2_000_000,
            "haiku": 5_000_000,
            "total": 3_000_000,
        },
        "7d": {
            "opus": 5_000_000,
            "sonnet": 15_000_000,
            "haiku": 50_000_000,
            "total": 20_000_000,
        },
    }
}

MODEL_NAMES = {
    "opus": "Opus",
    "sonnet": "Sonnet",
    "haiku": "Haiku",
}

# Progress bar config
BAR_WIDTH = 20
FILL_CHAR = "█"
EMPTY_CHAR = "░"


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                user_cfg = json.load(f)
            # Merge with defaults
            cfg = DEFAULT_CONFIG.copy()
            if "limits" in user_cfg:
                for window in ("5h", "7d"):
                    if window in user_cfg["limits"]:
                        cfg["limits"][window].update(user_cfg["limits"][window])
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
        return "#EF4444"  # red
    if pct >= 70:
        return "#F59E0B"  # amber
    if pct >= 50:
        return "#FBBF24"  # yellow
    return "#10B981"  # green


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


def render_window(label, usage_dict, limits, msg_count, color):
    total_out = total_output(usage_dict)
    total_limit = limits.get("total", 1)
    bar, pct = progress_bar(total_out, total_limit)
    bc = bar_color(pct)

    print(f"{label} — {pct:.0f}% | size=14 color={color}")
    print(f"--{bar} {pct:.0f}% ({fmt_tokens(total_out)}/{fmt_tokens(total_limit)}) | font=Menlo size=12 color={bc}")
    print(f"--Messages: {msg_count} | font=Menlo size=12")
    print("-----")

    # Per-model bars
    for model_key in ("opus", "sonnet", "haiku"):
        out = model_output(usage_dict, model_key)
        model_limit = limits.get(model_key, 0)
        if model_limit <= 0 and out == 0:
            continue
        m_bar, m_pct = progress_bar(out, model_limit)
        mc = bar_color(m_pct)
        name = friendly_model(model_key)
        print(f"--{name} | size=12")
        print(f"----{m_bar} {m_pct:.0f}% | font=Menlo size=11 color={mc}")
        print(f"----{fmt_tokens(out)} / {fmt_tokens(model_limit)} output | font=Menlo size=11")

    # Other models (if any)
    for model_key in sorted(usage_dict.keys()):
        if model_key in ("opus", "sonnet", "haiku"):
            continue
        out = usage_dict[model_key]["output"]
        if out > 0:
            name = friendly_model(model_key)
            print(f"--{name}: {fmt_tokens(out)} output | font=Menlo size=11")


def render():
    config = load_config()
    data = parse_logs()
    limits_5h = config["limits"]["5h"]
    limits_7d = config["limits"]["7d"]

    # Menu bar title — show highest percentage between 5h and 7d
    total_out_5h = total_output(data["5h"])
    total_out_7d = total_output(data["7d"])
    pct_5h = (total_out_5h / limits_5h["total"] * 100) if limits_5h["total"] > 0 else 0
    pct_7d = (total_out_7d / limits_7d["total"] * 100) if limits_7d["total"] > 0 else 0

    # Also check per-model percentages (Opus often hits limit first)
    max_pct = max(pct_5h, pct_7d)
    title_window = "5h" if pct_5h >= pct_7d else "7d"
    for model_key in ("opus", "sonnet", "haiku"):
        for window, limits, usage in [("5h", limits_5h, data["5h"]), ("7d", limits_7d, data["7d"])]:
            model_limit = limits.get(model_key, 0)
            if model_limit > 0:
                model_pct = model_output(usage, model_key) / model_limit * 100
                if model_pct > max_pct:
                    max_pct = model_pct
                    title_window = f"{window} {friendly_model(model_key)}"

    if total_out_5h == 0 and total_out_7d == 0:
        title = "C: idle"
    else:
        # Compact bar in menu bar title (8 chars wide)
        mini_bar, _ = progress_bar(max_pct, 100, width=8)
        title = f"C: {mini_bar} {max_pct:.0f}%"

    # Color the title based on severity
    tc = bar_color(max_pct)
    print(f"{title} | sfimage=brain.head.profile color={tc}")
    print("---")

    # 5-hour window
    render_window("5-Hour Window", data["5h"], limits_5h, data["messages_5h"], "#7C3AED")

    print("---")

    # 7-day window
    render_window("7-Day Window", data["7d"], limits_7d, data["messages_7d"], "#2563EB")

    print("---")

    # Cache summary
    cache_r_5h = sum(v["cache_read"] for v in data["5h"].values())
    cache_c_5h = sum(v["cache_create"] for v in data["5h"].values())
    cache_r_7d = sum(v["cache_read"] for v in data["7d"].values())
    cache_c_7d = sum(v["cache_create"] for v in data["7d"].values())
    print(f"Cache (5h): {fmt_tokens(cache_r_5h)} read, {fmt_tokens(cache_c_5h)} write | size=11 color=gray")
    print(f"Cache (7d): {fmt_tokens(cache_r_7d)} read, {fmt_tokens(cache_c_7d)} write | size=11 color=gray")

    print("---")

    # Config hint
    print(f"Limits: {CONFIG_PATH} | size=10 color=gray")
    print(f"--Edit config to adjust limits | size=11 bash=open param1={CONFIG_PATH} terminal=false")
    if not os.path.exists(CONFIG_PATH):
        print(f"--Create default config | size=11 bash=python3 param1=-c param2=import\\ json;open('{CONFIG_PATH}','w').write(json.dumps({json.dumps(DEFAULT_CONFIG)},indent=2)) terminal=false refresh=true")

    print("---")
    print("Refresh | refresh=true")
    now_str = datetime.now().strftime("%H:%M")
    print(f"Updated {now_str} | size=10 color=gray")


if __name__ == "__main__":
    render()
