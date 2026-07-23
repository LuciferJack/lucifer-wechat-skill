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

wechat-cli reads WeChat's local SQLite database. The database is encrypted, `init` extracts the decryption key from WeChat's process memory. This requires several macOS security restrictions to be relaxed.

#### Step 1: Disable SIP (System Integrity Protection)

SIP blocks `task_for_pid`, which is needed to read WeChat's process memory for the database key.

1. Shut down your Mac
2. Boot into Recovery Mode:
   - Apple Silicon: hold Power button until "Loading startup options" appears, select Options
   - Intel: hold Cmd+R during boot
3. Open Terminal from the menu bar (Utilities > Terminal)
4. Run: `csrutil disable`
5. Restart

Verify: `csrutil status` should show "disabled".

> You can re-enable SIP after init succeeds (`csrutil enable` in Recovery Mode). wechat-cli only needs the key once — subsequent queries use the saved key file.

#### Step 2: Grant Full Disk Access to Terminal

WeChat's database is in `~/Library/Containers/com.tencent.xinWeChat/`, which is sandboxed by macOS. Terminal needs Full Disk Access to read it.

1. System Settings > Privacy & Security > Full Disk Access
2. Click "+" and add your terminal app (Terminal.app, iTerm2, or whichever you use)
3. Restart the terminal

If you use Claude Code's desktop app, also grant Full Disk Access to it.

#### Step 3: Run init (WeChat must be running and logged in)

```bash
sudo ~/.claude/skills/lucifer-wechat-skill/bin/wechat-cli init
```

This will:
- Find the running WeChat process
- Extract database decryption keys from its memory
- Save keys to `~/.wechat-cli/all_keys.json`
- Auto-detect and save the database path to `~/.wechat-cli/config.json`

Verify: `~/.claude/skills/lucifer-wechat-skill/bin/wechat-cli sessions --limit 5` should list your recent chats.

#### Troubleshooting

| Problem | Solution |
|---------|----------|
| `task_for_pid failed` | SIP is still enabled, or WeChat needs re-signing: `codesign --remove-signature /Applications/WeChat.app && codesign --sign - /Applications/WeChat.app`, then relaunch WeChat and retry init |
| `permission denied` on db files | Full Disk Access not granted; check Step 2 |
| Wrong account's data | Multiple WeChat accounts have separate `wxid_*` directories. Edit `~/.wechat-cli/config.json` and set `db_dir` to the correct path |
| `~/.wechat-cli` permission errors | `sudo chown -R $(whoami):staff ~/.wechat-cli/` |
| WeChat updated, queries return empty | Re-run `sudo wechat-cli init --force` to re-extract keys (database encryption key may change after updates) |

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
