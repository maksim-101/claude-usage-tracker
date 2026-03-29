#!/usr/bin/env python3
"""
Claude Code + GSD Usage Tracker — SwiftBar plugin
Parses local JSONL logs from ~/.claude/projects/ and ~/.gsd/projects/ to
display token usage, cache efficiency, project activity, and git status.
100% offline — no network calls, no data leaves your machine.

NOTE: Only tracks Claude Code and GSD (gsd-pi) usage. Web (claude.ai) usage
is not captured but counts toward the same limits.
"""

import json
import os
import glob
import subprocess
from datetime import datetime, timezone, timedelta
from collections import defaultdict

CLAUDE_DIR = os.path.expanduser("~/.claude/projects")
PROJECTS_DIR = os.path.expanduser("~/code")
RATE_LIMITS_FILE = os.path.expanduser("~/.claude/.rate_limits")

# SwiftBar runs with a minimal PATH — ensure common tool locations are included
for p in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]:
    if p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = p + ":" + os.environ.get("PATH", "")

MODEL_NAMES = {
    "opus": "Opus",
    "sonnet": "Sonnet",
    "haiku": "Haiku",
}

# Display name overrides for projects whose encoded dir names lose characters
DISPLAY_NAMES = {
    "Selbstst-ndigkeit": "Selbstständigkeit",
    "Digital-Solutions-Platform": "Digital Solutions Platform",
}

SPARK_CHARS = "▁▂▃▄▅▆▇█"

# Rate limit staleness threshold (minutes) — ignore data older than this
RATE_LIMIT_STALE_MINUTES = 30


# ── Helpers ──────────────────────────────────────────────────────────────────


def read_rate_limits():
    """Read rate limit data written by statusline.sh.

    Returns dict with five_hour_pct and resets_at, or None if stale/missing.
    """
    try:
        with open(RATE_LIMITS_FILE, "r") as f:
            data = json.loads(f.read().strip())
        ts = data.get("ts", 0)
        age_minutes = (datetime.now().timestamp() - ts) / 60
        if age_minutes > RATE_LIMIT_STALE_MINUTES:
            return None
        return data
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def progress_bar(pct, width=10):
    """Return a colored progress bar string for SwiftBar."""
    filled = int(pct * width / 100)
    empty = width - filled
    return "█" * filled + "░" * empty


def bar_color(pct):
    """Color for rate limit bar — green/yellow/red."""
    if pct >= 90:
        return "#EF4444"   # red
    if pct >= 70:
        return "#FBBF24"   # yellow
    return "#10B981"       # green


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


def sparkline(values):
    """Return a sparkline string for a list of numeric values."""
    if not values or max(values) == 0:
        return SPARK_CHARS[0] * len(values)
    peak = max(values)
    return "".join(
        SPARK_CHARS[min(int(v / peak * (len(SPARK_CHARS) - 1)), len(SPARK_CHARS) - 1)]
        for v in values
    )


def extract_project_name(filepath):
    """Extract a friendly project name from a JSONL file path."""
    rel = os.path.relpath(filepath, CLAUDE_DIR)
    project_dir = rel.split(os.sep)[0]

    if project_dir == "-Users-mowehr--claude":
        return ".claude"

    prefixes = [
        "-Users-mowehr-code-",
        "-Users-mowehr-Documents-claude-projects-",
        "-Users-mowehr-",
    ]
    for prefix in prefixes:
        if project_dir.startswith(prefix):
            name = project_dir[len(prefix):] or project_dir
            return DISPLAY_NAMES.get(name, name)

    name = project_dir.lstrip("-") or project_dir
    return DISPLAY_NAMES.get(name, name)


def day_label(dt):
    """Short weekday label for a date."""
    return dt.strftime("%a")


GSD_SESSIONS_DIR = os.path.expanduser("~/.gsd/sessions")


def extract_gsd_session_project_name(filepath):
    """Extract a friendly project name from a GSD session JSONL path.

    Session dirs are named like --Users-mowehr-code-vaca-dia--
    Strip the leading/trailing -- and extract the last path component.
    """
    rel = os.path.relpath(filepath, GSD_SESSIONS_DIR)
    session_dir = rel.split(os.sep)[0]

    # Strip leading/trailing --
    cleaned = session_dir.strip("-")

    # Try to get just the repo folder name from the encoded path
    # e.g. "Users-mowehr-code-vaca-dia" -> "vaca-dia"
    if cleaned:
        # The path uses - as separator; take the last segment
        # Handle known prefixes to get the project name
        for prefix in [
            "Users-mowehr-code-",
            "Users-mowehr-Documents-claude-projects-",  # legacy path
            "Users-mowehr-",
        ]:
            if cleaned.startswith(prefix):
                name = cleaned[len(prefix):] or cleaned
                return f"{DISPLAY_NAMES.get(name, name)} (gsd)"

        # If .claude path
        if cleaned == "Users-mowehr-.claude-" or cleaned == "Users-mowehr-.claude":
            return ".claude (gsd)"

        name = cleaned.split("-")[-1] if "-" in cleaned else cleaned
        return f"{name} (gsd)"

    return f"{session_dir} (gsd)"


# ── Log Parsing ──────────────────────────────────────────────────────────────


def parse_logs():
    """Parse JSONL logs and return structured usage data.

    Returns dict with:
      - today: by_model, by_project, cache, messages
      - week: by_model, by_project, cache, messages
      - daily: {date_str: output_tokens} for sparkline
      - project_last_active: {project: datetime}
    """
    now = datetime.now(timezone.utc)
    local_now = datetime.now().astimezone()
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Monday of this week (ISO weekday: Mon=1)
    week_start = (local_now - timedelta(days=local_now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # We need 7 days back for the sparkline
    cutoff = week_start

    def new_bucket():
        return {
            "by_model": defaultdict(lambda: {"input": 0, "output": 0}),
            "by_project": defaultdict(lambda: {"input": 0, "output": 0}),
            "cache": {"read": 0, "create": 0, "fresh_input": 0},
            "messages": 0,
        }

    today_data = new_bucket()
    week_data = new_bucket()

    # Daily output tokens for sparkline (Mon-Sun of current week)
    daily_output = defaultdict(int)

    # Track last activity per project
    project_last_active = {}

    jsonl_files = glob.glob(os.path.join(CLAUDE_DIR, "**", "*.jsonl"), recursive=True)

    for filepath in jsonl_files:
        try:
            mtime = os.path.getmtime(filepath)
            if datetime.fromtimestamp(mtime, tz=timezone.utc) < cutoff.astimezone(timezone.utc):
                continue
        except OSError:
            continue

        project = extract_project_name(filepath)

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

                    ts_local = ts.astimezone(local_now.tzinfo)
                    if ts_local < cutoff:
                        continue

                    # Track last active
                    if project not in project_last_active or ts_local > project_last_active[project]:
                        project_last_active[project] = ts_local

                    model = classify_model(msg.get("model", ""))
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    cache_read = usage.get("cache_read_input_tokens", 0)
                    cache_create = usage.get("cache_creation_input_tokens", 0)
                    # input_tokens is already the fresh (non-cached) input count
                    fresh_input = input_tokens

                    # Daily sparkline bucket
                    day_key = ts_local.strftime("%Y-%m-%d")
                    daily_output[day_key] += output_tokens

                    # Week bucket
                    if ts_local >= week_start:
                        w = week_data
                        w["by_model"][model]["input"] += input_tokens
                        w["by_model"][model]["output"] += output_tokens
                        w["by_project"][project]["input"] += input_tokens
                        w["by_project"][project]["output"] += output_tokens
                        w["cache"]["read"] += cache_read
                        w["cache"]["create"] += cache_create
                        w["cache"]["fresh_input"] += fresh_input
                        w["messages"] += 1

                    # Today bucket
                    if ts_local >= today_start:
                        d = today_data
                        d["by_model"][model]["input"] += input_tokens
                        d["by_model"][model]["output"] += output_tokens
                        d["by_project"][project]["input"] += input_tokens
                        d["by_project"][project]["output"] += output_tokens
                        d["cache"]["read"] += cache_read
                        d["cache"]["create"] += cache_create
                        d["cache"]["fresh_input"] += fresh_input
                        d["messages"] += 1

        except (OSError, PermissionError):
            continue

    # ── GSD (gsd-pi) session logs ──
    # Uses different field names: input/output/cacheRead/cacheWrite
    gsd_session_files = glob.glob(
        os.path.join(GSD_SESSIONS_DIR, "**", "*.jsonl"), recursive=True
    )

    for filepath in gsd_session_files:
        try:
            mtime = os.path.getmtime(filepath)
            if datetime.fromtimestamp(mtime, tz=timezone.utc) < cutoff.astimezone(timezone.utc):
                continue
        except OSError:
            continue

        project = extract_gsd_session_project_name(filepath)

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

                    ts_local = ts.astimezone(local_now.tzinfo)
                    if ts_local < cutoff:
                        continue

                    if project not in project_last_active or ts_local > project_last_active[project]:
                        project_last_active[project] = ts_local

                    model = classify_model(msg.get("model", ""))
                    # GSD uses shorthand keys (no _tokens suffix)
                    input_tokens = usage.get("input", 0)
                    output_tokens = usage.get("output", 0)
                    cache_read = usage.get("cacheRead", 0)
                    cache_create = usage.get("cacheWrite", 0)
                    fresh_input = input_tokens

                    day_key = ts_local.strftime("%Y-%m-%d")
                    daily_output[day_key] += output_tokens

                    if ts_local >= week_start:
                        w = week_data
                        w["by_model"][model]["input"] += input_tokens
                        w["by_model"][model]["output"] += output_tokens
                        w["by_project"][project]["input"] += input_tokens
                        w["by_project"][project]["output"] += output_tokens
                        w["cache"]["read"] += cache_read
                        w["cache"]["create"] += cache_create
                        w["cache"]["fresh_input"] += fresh_input
                        w["messages"] += 1

                    if ts_local >= today_start:
                        d = today_data
                        d["by_model"][model]["input"] += input_tokens
                        d["by_model"][model]["output"] += output_tokens
                        d["by_project"][project]["input"] += input_tokens
                        d["by_project"][project]["output"] += output_tokens
                        d["cache"]["read"] += cache_read
                        d["cache"]["create"] += cache_create
                        d["cache"]["fresh_input"] += fresh_input
                        d["messages"] += 1

        except (OSError, PermissionError):
            continue

    # Build ordered daily values (Mon through today)
    days_so_far = (local_now - week_start).days + 1
    daily_values = []
    daily_labels = []
    for i in range(days_so_far):
        day = week_start + timedelta(days=i)
        key = day.strftime("%Y-%m-%d")
        daily_values.append(daily_output.get(key, 0))
        daily_labels.append(day.strftime("%a"))

    return {
        "today": today_data,
        "week": week_data,
        "daily_values": daily_values,
        "daily_labels": daily_labels,
        "project_last_active": project_last_active,
    }


def total_output(by_model):
    return sum(v["output"] for v in by_model.values())


def total_input(by_model):
    return sum(v["input"] for v in by_model.values())


def cache_hit_ratio(cache):
    """Return cache hit ratio as a percentage."""
    total = cache["read"] + cache["fresh_input"]
    if total == 0:
        return 0
    return cache["read"] / total * 100


def cache_color(ratio):
    """Color code for cache hit ratio — higher is better (inverse of bar_color)."""
    if ratio >= 90:
        return "#10B981"  # green — excellent
    if ratio >= 70:
        return "#FBBF24"  # yellow — decent
    if ratio >= 50:
        return "#F59E0B"  # orange — mediocre
    return "#EF4444"      # red — poor


# ── Git Integration ──────────────────────────────────────────────────────────


def git_status_all():
    """Check git status for all repos in PROJECTS_DIR.

    Returns list of (project_name, dirty_count, unpushed_count).
    Only includes repos with uncommitted changes or unpushed commits.
    """
    results = []
    try:
        entries = sorted(os.listdir(PROJECTS_DIR))
    except (PermissionError, OSError):
        return results

    for name in entries:
        repo = os.path.join(PROJECTS_DIR, name)
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        try:
            # Count dirty files (modified + untracked)
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo, capture_output=True, text=True, timeout=5
            )
            dirty = len([l for l in status.stdout.strip().split("\n") if l.strip()]) if status.stdout.strip() else 0

            # Count unpushed commits
            unpushed = 0
            tracking = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                cwd=repo, capture_output=True, text=True, timeout=5
            )
            if tracking.returncode == 0:
                ahead = subprocess.run(
                    ["git", "rev-list", "--count", "@{u}..HEAD"],
                    cwd=repo, capture_output=True, text=True, timeout=5
                )
                if ahead.returncode == 0:
                    unpushed = int(ahead.stdout.strip())

            if dirty > 0 or unpushed > 0:
                results.append((name, dirty, unpushed))
        except (subprocess.TimeoutExpired, OSError, ValueError):
            continue

    return results


def open_prs():
    """Get open PRs across all repos via gh CLI.

    Returns list of (repo_name, pr_count) or None on failure.
    """
    results = []
    try:
        entries = sorted(os.listdir(PROJECTS_DIR))
    except (PermissionError, OSError):
        return None

    for name in entries:
        repo = os.path.join(PROJECTS_DIR, name)
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        try:
            result = subprocess.run(
                ["gh", "pr", "list", "--state", "open", "--json", "number,title"],
                cwd=repo, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                prs = json.loads(result.stdout)
                if prs:
                    results.append((name, prs))
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
            continue

    return results


# ── Render ───────────────────────────────────────────────────────────────────


def render_section(label, color, data):
    """Render a Today or This Week section."""
    out = total_output(data["by_model"])
    inp = total_input(data["by_model"])
    print(f"{label} | size=14 color={color}")
    print(f"--{fmt_tokens(out)} output, {fmt_tokens(inp)} input | font=Menlo size=12")
    print(f"--{data['messages']} messages | font=Menlo size=12")

    if data["by_model"]:
        print("-----")
        print("--By Model | size=12")
        for model_key in ("opus", "sonnet", "haiku"):
            m = data["by_model"].get(model_key)
            if m and (m["output"] > 0 or m["input"] > 0):
                print(f"----{friendly_model(model_key)}: {fmt_tokens(m['output'])} out, {fmt_tokens(m['input'])} in | font=Menlo size=11")
        print("--By Project | size=12")
        for proj, tokens in sorted(data["by_project"].items(), key=lambda x: x[1]["output"], reverse=True):
            if tokens["output"] > 0:
                print(f"----{proj}: {fmt_tokens(tokens['output'])} out, {fmt_tokens(tokens['input'])} in | font=Menlo size=11")


def render():
    data = parse_logs()

    out_today = total_output(data["today"]["by_model"])
    out_week = total_output(data["week"]["by_model"])

    # ── Rate Limits ──
    rate = read_rate_limits()

    # ── Menu Bar ──
    if out_today == 0 and out_week == 0:
        title = "C: idle"
    else:
        title = f"C: {fmt_tokens(out_today)}"

    # Append compact rate limit to menu bar title if available
    if rate:
        pct = rate["five_hour_pct"]
        title += f"  5h:{pct}%"

    print(f"{title} | sfimage=brain.head.profile")

    print("---")

    # ── 5-Hour Usage Limit ──
    if rate:
        pct = rate["five_hour_pct"]
        color = bar_color(pct)
        bar = progress_bar(pct)
        label = "5-Hour Usage Limit"
        if pct >= 90:
            label += " — SLOW DOWN"
        print(f"{label} | size=14 color={color}")
        print(f"--{bar}  {pct}% | font=Menlo size=13 color={color}")
        resets_at = rate.get("resets_at", "")
        if resets_at:
            try:
                # Try as Unix timestamp first, then ISO 8601
                try:
                    reset_dt = datetime.fromtimestamp(int(resets_at), tz=timezone.utc)
                except (ValueError, TypeError):
                    reset_dt = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
                reset_local = reset_dt.astimezone(datetime.now().astimezone().tzinfo)
                print(f"--Resets at {reset_local.strftime('%H:%M')} | font=Menlo size=11 color=gray")
            except (ValueError, AttributeError, OSError):
                pass
        print("---")

    # ── Today ──
    render_section("Today", "#7C3AED", data["today"])

    print("---")

    # ── This Week ──
    render_section("This Week", "#2563EB", data["week"])

    # Weekly sparkline chart — one line per day for alignment
    if data["daily_values"]:
        print("-----")
        print("--Daily Output | size=12")
        peak = max(data["daily_values"]) if data["daily_values"] else 0
        for label, value in zip(data["daily_labels"], data["daily_values"]):
            bar_char = SPARK_CHARS[min(int(value / peak * (len(SPARK_CHARS) - 1)), len(SPARK_CHARS) - 1)] if peak > 0 else SPARK_CHARS[0]
            bar = bar_char * 8
            print(f"----{label}  {bar}  {fmt_tokens(value):>6} | font=Menlo size=11")

    print("---")

    # ── Cache Efficiency ──
    today_ratio = cache_hit_ratio(data["today"]["cache"])
    week_ratio = cache_hit_ratio(data["week"]["cache"])
    tc = data["today"]["cache"]
    wc = data["week"]["cache"]

    tc_color = cache_color(today_ratio)
    wc_color = cache_color(week_ratio)
    print(f"Cache Efficiency | size=14 color=#0891B2")
    print(f"--Today: {today_ratio:.1f}% hit ratio | font=Menlo size=12 color={tc_color}")
    print(f"----{fmt_tokens(tc['read'])} read, {fmt_tokens(tc['create'])} created, {fmt_tokens(tc['fresh_input'])} fresh | font=Menlo size=11")
    print(f"--Week:  {week_ratio:.1f}% hit ratio | font=Menlo size=12 color={wc_color}")
    print(f"----{fmt_tokens(wc['read'])} read, {fmt_tokens(wc['create'])} created, {fmt_tokens(wc['fresh_input'])} fresh | font=Menlo size=11")

    print("---")

    # ── Projects ──
    print(f"Projects | size=14 color=#059669")
    active = data["project_last_active"]
    if active:
        now = datetime.now().astimezone()
        for proj, last in sorted(active.items(), key=lambda x: x[1], reverse=True):
            ago = now - last
            if ago.total_seconds() < 60:
                ago_str = "just now"
            elif ago.total_seconds() < 3600:
                ago_str = f"{int(ago.total_seconds() / 60)}m ago"
            elif ago.total_seconds() < 86400:
                ago_str = f"{int(ago.total_seconds() / 3600)}h ago"
            else:
                ago_str = f"{int(ago.days)}d ago"

            out = data["week"]["by_project"].get(proj, {}).get("output", 0)
            print(f"--{proj} — {ago_str} ({fmt_tokens(out)} this week) | font=Menlo size=11")
    else:
        print("--No activity this week | size=11 color=gray")

    print("---")

    # ── Git Status ──
    print(f"Git | size=14 color=#DC2626")
    repos = git_status_all()
    if repos:
        for name, dirty, unpushed in repos:
            parts = []
            if dirty:
                parts.append(f"{dirty} dirty")
            if unpushed:
                parts.append(f"{unpushed} unpushed")
            print(f"--{name}: {', '.join(parts)} | font=Menlo size=11")
    else:
        print("--All clean | font=Menlo size=11 color=#10B981")

    # Open PRs (non-blocking — skip if gh is slow)
    pr_data = open_prs()
    if pr_data is not None:
        if pr_data:
            total_prs = sum(len(prs) for _, prs in pr_data)
            print(f"--{total_prs} open PR{'s' if total_prs != 1 else ''} | font=Menlo size=11 color=#F59E0B")
            for repo_name, prs in pr_data:
                for pr in prs:
                    print(f"----{repo_name}: #{pr['number']} {pr.get('title', '')} | font=Menlo size=10")
        else:
            print(f"--No open PRs | font=Menlo size=11 color=gray")

    print("---")

    # ── Footer ──
    print("Claude Code + GSD — web usage not tracked | size=10 color=#F59E0B")
    print("---")
    print("Refresh | refresh=true")
    now_str = datetime.now().strftime("%H:%M")
    print(f"Updated {now_str} | size=10 color=gray")


if __name__ == "__main__":
    render()
