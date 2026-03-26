# Claude Usage Tracker

A lightweight macOS menu bar plugin that tracks your Claude Code and [GSD](https://gsd.quest) (gsd-pi) token usage. Built with [SwiftBar](https://github.com/swiftbar/SwiftBar).

**100% offline** — parses local log files only. No data leaves your machine.

![Menu Bar Example](https://img.shields.io/badge/macOS-menu%20bar-blue)

## What It Shows

- **Today / This Week** — output and input token totals with message counts
- **By Model** — breakdown across Opus, Sonnet, and Haiku
- **By Project** — per-project token usage (Claude Code projects + GSD projects)
- **Daily Output Sparkline** — visual chart of output tokens per day for the current week
- **Cache Efficiency** — hit ratio with color-coded indicators (green/yellow/orange/red)
- **Project Activity** — last-active timestamps and weekly output per project
- **Git Status** — dirty files and unpushed commits across all repos
- **Open PRs** — open pull requests via `gh` CLI

The menu bar title shows today's output token count at a glance.

## Data Sources

| Source | Log Location | Description |
|--------|-------------|-------------|
| Claude Code | `~/.claude/projects/**/*.jsonl` | Direct Claude Code sessions and subagent logs |
| GSD (gsd-pi) | `~/.gsd/sessions/**/*.jsonl` | GSD autonomous agent session logs |

GSD projects are labeled with a `(gsd)` suffix in the project breakdown.

**Note:** Web usage from claude.ai, the desktop app, or the iOS app counts toward the same rate limits but is not captured here.

## Requirements

- macOS 14.0+ (Sonoma)
- [SwiftBar](https://github.com/swiftbar/SwiftBar) — `brew install --cask swiftbar`
- Python 3 (included with macOS)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (the logs it generates are what we read)
- Optional: [GSD](https://gsd.quest) (gsd-pi) for autonomous agent tracking

## Installation

1. Install SwiftBar:
   ```bash
   brew install --cask swiftbar
   ```

2. Clone this repo:
   ```bash
   git clone https://github.com/maksim-101/claude-usage-tracker.git
   cd claude-usage-tracker
   ```

3. Deploy the plugin:
   ```bash
   ./deploy.sh
   ```

4. Launch SwiftBar and point it to `~/Library/Application Support/SwiftBar/Plugins/` if prompted.

## Updating

After pulling changes or editing the plugin:

```bash
./deploy.sh
```

Then click **Refresh** in the SwiftBar menu.

## Privacy

- Reads only from local log files (`~/.claude/projects/`, `~/.gsd/sessions/`)
- No network calls whatsoever (except `gh pr list` for open PRs, which is optional)
- No telemetry, analytics, or external services

## License

MIT
