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
WINDOW_5H = timedelta(hours=5)
WINDOW_7D = timedelta(days=7)

# Friendly model names
MODEL_NAMES = {
    "opus": "Opus",
    "sonnet": "Sonnet",
    "haiku": "Haiku",
}


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
    """Format token count with K/M suffix."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def parse_logs():
    """Parse all JSONL logs and extract usage data with timestamps."""
    now = datetime.now(timezone.utc)
    cutoff_5h = now - WINDOW_5H
    cutoff_7d = now - WINDOW_7D

    usage_5h = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0})
    usage_7d = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0})
    session_count_5h = set()
    session_count_7d = set()
    message_count_5h = 0
    message_count_7d = 0

    jsonl_files = glob.glob(os.path.join(CLAUDE_DIR, "**", "*.jsonl"), recursive=True)

    for filepath in jsonl_files:
        # Quick check: skip files not modified in last 7 days
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

                    # Only count assistant messages with usage data
                    msg = entry.get("message", {})
                    if not isinstance(msg, dict):
                        continue
                    usage = msg.get("usage")
                    if not usage:
                        continue
                    if msg.get("role") != "assistant":
                        continue

                    # Parse timestamp
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
                    session_id = entry.get("sessionId", "")

                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    cache_read = usage.get("cache_read_input_tokens", 0)
                    cache_create = usage.get("cache_creation_input_tokens", 0)

                    # 7-day window
                    usage_7d[model]["input"] += input_tokens
                    usage_7d[model]["output"] += output_tokens
                    usage_7d[model]["cache_read"] += cache_read
                    usage_7d[model]["cache_create"] += cache_create
                    session_count_7d.add(session_id)
                    message_count_7d += 1

                    # 5-hour window
                    if ts >= cutoff_5h:
                        usage_5h[model]["input"] += input_tokens
                        usage_5h[model]["output"] += output_tokens
                        usage_5h[model]["cache_read"] += cache_read
                        usage_5h[model]["cache_create"] += cache_create
                        session_count_5h.add(session_id)
                        message_count_5h += 1

        except (OSError, PermissionError):
            continue

    return {
        "5h": usage_5h,
        "7d": usage_7d,
        "sessions_5h": len(session_count_5h),
        "sessions_7d": len(session_count_7d),
        "messages_5h": message_count_5h,
        "messages_7d": message_count_7d,
    }


def total_tokens(usage_dict):
    """Sum all token types across all models."""
    total_in = sum(v["input"] for v in usage_dict.values())
    total_out = sum(v["output"] for v in usage_dict.values())
    total_cache_r = sum(v["cache_read"] for v in usage_dict.values())
    total_cache_c = sum(v["cache_create"] for v in usage_dict.values())
    return total_in, total_out, total_cache_r, total_cache_c


def render():
    data = parse_logs()

    # Menu bar title — compact summary
    total_in_5h, total_out_5h, _, _ = total_tokens(data["5h"])
    total_5h = total_in_5h + total_out_5h
    total_in_7d, total_out_7d, _, _ = total_tokens(data["7d"])
    total_7d = total_in_7d + total_out_7d

    # Title: show 5h usage (most relevant for rate limits)
    if total_5h == 0:
        title = "C: idle"
    else:
        title = f"C: {fmt_tokens(total_out_5h)}↑ 5h"

    print(f"{title} | sfimage=brain.head.profile")
    print("---")

    # 5-hour window
    print(f"Last 5 Hours | size=14 color=#7C3AED")
    print(f"--Output: {fmt_tokens(total_out_5h)} | font=Menlo size=12")
    print(f"--Input: {fmt_tokens(total_in_5h)} | font=Menlo size=12")
    print(f"--Messages: {data['messages_5h']} | font=Menlo size=12")
    print(f"--Sessions: {data['sessions_5h']} | font=Menlo size=12")
    if data["5h"]:
        print("--Per Model | size=12")
        for model_key in sorted(data["5h"].keys()):
            u = data["5h"][model_key]
            name = friendly_model(model_key)
            print(f"----{name}: {fmt_tokens(u['output'])}↑ {fmt_tokens(u['input'])}↓ | font=Menlo size=11")

    print("---")

    # 7-day window
    print(f"Last 7 Days | size=14 color=#2563EB")
    print(f"--Output: {fmt_tokens(total_out_7d)} | font=Menlo size=12")
    print(f"--Input: {fmt_tokens(total_in_7d)} | font=Menlo size=12")
    print(f"--Messages: {data['messages_7d']} | font=Menlo size=12")
    print(f"--Sessions: {data['sessions_7d']} | font=Menlo size=12")
    if data["7d"]:
        print("--Per Model | size=12")
        for model_key in sorted(data["7d"].keys()):
            u = data["7d"][model_key]
            name = friendly_model(model_key)
            print(f"----{name}: {fmt_tokens(u['output'])}↑ {fmt_tokens(u['input'])}↓ | font=Menlo size=11")

    print("---")

    # Cache stats (useful context)
    _, _, cache_r_5h, cache_c_5h = total_tokens(data["5h"])
    _, _, cache_r_7d, cache_c_7d = total_tokens(data["7d"])
    print(f"Cache (5h): {fmt_tokens(cache_r_5h)} read, {fmt_tokens(cache_c_5h)} created | size=11 color=gray")
    print(f"Cache (7d): {fmt_tokens(cache_r_7d)} read, {fmt_tokens(cache_c_7d)} created | size=11 color=gray")

    print("---")
    print("Refresh | refresh=true")
    now_str = datetime.now().strftime("%H:%M")
    print(f"Updated {now_str} | size=10 color=gray")


if __name__ == "__main__":
    render()
