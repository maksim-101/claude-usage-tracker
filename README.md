# Claude Usage Tracker

A lightweight macOS menu bar plugin that tracks your Claude Code token usage against rate limit windows. Built with [SwiftBar](https://github.com/swiftbar/SwiftBar).

**100% offline** — parses local log files only. No data leaves your machine.

![Menu Bar Example](https://img.shields.io/badge/macOS-menu%20bar-blue)

## What It Shows

- **Current Session (5h)** — progress bar with output token count and percentage
- **Weekly Limits** — "All Models" and "Sonnet Only" bars, matching claude.ai's layout
- **Per-model breakdown** — Opus, Sonnet, Haiku with share percentages
- **Color-coded bars** — green → yellow → amber → red as usage increases

The menu bar title shows the highest usage percentage across all windows so you can see at a glance how close you are to any limit.

## How It Works

Claude Code stores conversation logs as JSONL files in `~/.claude/projects/`. This plugin parses those files, sums token usage within the 5-hour and 7-day windows, and displays the results via SwiftBar. No API calls, no network requests.

**Note:** Only Claude Code usage is tracked. Usage from claude.ai web, desktop app, or iOS app counts toward the same limits but won't appear here.

## Requirements

- macOS 14.0+ (Sonoma)
- [SwiftBar](https://github.com/swiftbar/SwiftBar) — `brew install --cask swiftbar`
- Python 3 (included with macOS)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (the logs it generates are what we read)

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

## Configuration

Limits are configurable via `~/.claude/usage-tracker-config.json`. Create it from the SwiftBar menu (Settings → Create default config) or manually:

```json
{
  "limits": {
    "5h": {
      "total": 2000000
    },
    "7d": {
      "all_models": 13000000,
      "sonnet": 7000000
    }
  }
}
```

Values are in **output tokens**. The defaults are calibrated for the Max 5x plan ($100/mo). Adjust based on your subscription tier and what you observe in claude.ai's usage page.

## Updating

After pulling changes or editing the plugin:

```bash
./deploy.sh
```

Then click **Refresh** in the SwiftBar menu.

## Privacy

- Reads only from `~/.claude/projects/*.jsonl` (local Claude Code logs)
- No network calls whatsoever
- No telemetry, analytics, or external services
- Config stored locally at `~/.claude/usage-tracker-config.json`

## License

MIT
