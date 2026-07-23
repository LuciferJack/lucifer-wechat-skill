#!/bin/bash
set -e

SKILL_DIR="$HOME/.claude/skills/lucifer-wechat-skill"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== lucifer-wechat-skill installer ==="

# 1. Create skill directory
mkdir -p "$SKILL_DIR/bin"

# 2. Copy skill files
cp "$SCRIPT_DIR/SKILL.md" "$SKILL_DIR/SKILL.md"
cp "$SCRIPT_DIR/wechat_send.py" "$SKILL_DIR/wechat_send.py"
echo "[OK] Skill files installed to $SKILL_DIR"

# 3. Install wechat-cli binary
if [ -f "$SKILL_DIR/bin/wechat-cli" ]; then
    echo "[OK] wechat-cli binary already exists, skipping download"
else
    ARCH="$(uname -m)"
    if [ "$ARCH" = "arm64" ]; then
        PKG="@canghe_ai/wechat-cli-darwin-arm64"
    elif [ "$ARCH" = "x86_64" ]; then
        PKG="@canghe_ai/wechat-cli-darwin-x64"
    else
        echo "[ERROR] Unsupported architecture: $ARCH"
        exit 1
    fi

    echo "Downloading wechat-cli binary for $ARCH..."
    TMPDIR="$(mktemp -d)"
    trap "rm -rf '$TMPDIR'" EXIT

    npm pack "$PKG" --pack-destination "$TMPDIR" --silent 2>/dev/null
    TAR="$(ls "$TMPDIR"/*.tgz 2>/dev/null | head -1)"
    if [ -z "$TAR" ]; then
        echo "[ERROR] Failed to download $PKG. Install npm first: brew install node"
        exit 1
    fi

    tar xzf "$TAR" -C "$TMPDIR"
    cp "$TMPDIR/package/bin/wechat-cli" "$SKILL_DIR/bin/wechat-cli"
    chmod +x "$SKILL_DIR/bin/wechat-cli"
    echo "[OK] wechat-cli binary installed"
fi

# 4. Verify
if "$SKILL_DIR/bin/wechat-cli" --version >/dev/null 2>&1; then
    VERSION="$("$SKILL_DIR/bin/wechat-cli" --version)"
    echo "[OK] wechat-cli verified: $VERSION"
else
    echo "[WARN] wechat-cli binary exists but failed to run"
fi

# 5. Check wechat-cli init status
if [ -d "$HOME/.wechat-cli" ] && [ -f "$HOME/.wechat-cli/config.json" ]; then
    echo "[OK] wechat-cli already initialized"
else
    echo ""
    echo "[ACTION REQUIRED] wechat-cli needs initialization."
    echo "  1. Disable SIP (csrutil disable in Recovery Mode)"
    echo "  2. Grant Full Disk Access to Terminal (System Settings > Privacy)"
    echo "  3. Run: sudo $SKILL_DIR/bin/wechat-cli init"
    echo ""
fi

echo ""
echo "=== Installation complete ==="
echo "Skill installed to: $SKILL_DIR"
echo "Use in Claude Code: just tell Claude to send a WeChat message."
