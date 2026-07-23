# lucifer-wechat-skill

Claude Code skill for sending WeChat messages on macOS.

Uses wechat-cli (local database lookup) + AppleScript keyboard automation + macOS Vision OCR to send text messages through WeChat Desktop.

## Requirements

- macOS 10.15+
- WeChat Desktop (logged in)
- Node.js / npm (for wechat-cli binary download)
- Terminal with Accessibility permission (System Settings > Privacy > Accessibility)

## Install

```bash
git clone https://github.com/LuciferJack/lucifer-wechat-skill.git
cd lucifer-wechat-skill
./install.sh
```

The install script:
1. Copies skill files to `~/.claude/skills/lucifer-wechat-skill/`
2. Downloads the platform-specific `wechat-cli` binary via npm
3. Checks initialization status

### wechat-cli initialization (first time only)

wechat-cli reads WeChat's local SQLite database. First-time setup requires:

1. **Disable SIP** (Recovery Mode > `csrutil disable`)
2. **Grant Full Disk Access** to Terminal (System Settings > Privacy & Security > Full Disk Access)
3. Run initialization with admin privileges:

```bash
sudo ~/.claude/skills/lucifer-wechat-skill/bin/wechat-cli init
```

If you hit `task_for_pid failed`, re-sign WeChat and retry.

## Usage

In Claude Code, just say things like:

- "send a WeChat message to John saying hi"
- "tell the group chat 'meeting at 3pm'"
- "send '报告已完成' to 文件传输助手"

Claude will:

1. **Pre-check** the contact/group exists via wechat-cli
2. **Confirm** target + message with you before sending
3. **Automate** WeChat GUI: search > OCR locate > click > type > send
4. **Verify** the message arrived via wechat-cli

## How it works

1. **Step 1**: wechat-cli contact lookup (exact/fuzzy match) + user confirmation
2. **Step 2**: Type target name in WeChat search bar, wait for popup
3. **Step 3**: Screenshot + Vision OCR to get screen coordinates
4. **Step 4**: Type again + click at known coordinates to open chat
5. **Step 5**: Screenshot verify correct chat opened (auto-retry up to 3x) + send message
6. **Step 6**: wechat-cli history check to confirm delivery

## Security

- Privacy content interception: passwords, bank cards, ID numbers, SSH keys, API keys, tokens are blocked
- User confirmation required before every send
- All data stays local (wechat-cli reads local DB, no network calls)

## License

MIT
