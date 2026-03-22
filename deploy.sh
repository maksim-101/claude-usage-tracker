#!/bin/bash
# Deploy the Claude usage tracker plugin to SwiftBar
PLUGIN="claude-usage.5m.py"
SRC="$(dirname "$0")/$PLUGIN"
DEST="$HOME/Library/Application Support/SwiftBar/Plugins/$PLUGIN"

cp "$SRC" "$DEST" && chmod +x "$DEST"
echo "Deployed $PLUGIN to SwiftBar plugins."
