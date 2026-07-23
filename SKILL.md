---
name: lucifer-wechat-skill
description: >-
  macOS 微信消息发送技能。通过 wechat-cli 预查 + AppleScript 键盘模拟 + Vision OCR 定位，发送文本消息到任意联系人或群聊。
  当用户需要发微信消息、给某人发消息、微信通知某人时使用。
version: 2.0.0
author: LuciferJack
platform: macOS
requirements:
  - macOS 10.15+
  - WeChat Desktop (已登录)
  - System Events 辅助功能权限
---

# Skill: lucifer-wechat-skill

macOS 微信文本消息发送。严格六步流程。

## 硬规则（无例外）

### 隐私内容拦截

以下内容**绝对禁止**发送，检测到即拒绝：密码、验证码、银行卡号、身份证号、SSH密钥、API Key、Token。

检测到违规内容时回复：`安全拦截：消息包含隐私敏感内容（{类型}），拒绝发送。`

## 发送流程

### 第一步：确认联系人 + 确认消息（与用户交互）

在任何 GUI 操作之前，先完成两件事：

1. 用 `--lookup-only` 确认联系人存在：

```bash
python3 ~/.claude/skills/lucifer-wechat-skill/wechat_send.py --target "目标名" --lookup-only
```

根据返回处理：
- `exact_match`：告知用户找到了，继续
- `fuzzy_match`：展示 suggestions 列表，问用户"你要发给哪个？"
- `CONTACT_NOT_FOUND`：告知未找到，建议检查名称

2. 展示目标 + 消息，等用户正面回复：

```
目标: {确认后的联系人名} | 消息: {完整文本}
```

等用户回复"发"/"好的"/"ok"/"行"/"成"/"没问题"等正面确认后，**立即执行第二~六步，一气呵成，中间不停顿。**

### 第二~六步：GUI 自动化（一气呵成）

用户确认后，一次调用完成：

```bash
python3 ~/.claude/skills/lucifer-wechat-skill/wechat_send.py --target "确认后的目标名" --message "消息内容" --skip-lookup
```

脚本内部执行：
- **第二步**：搜索框输入目标名，不点击，等2s，popup出现
- **第三步**：截图 + OCR 定位目标在 popup 中的屏幕坐标
- **第四步**：再次搜索框输入目标名，等2s，popup出现，点击坐标打开聊天
- **第五步**：截图确认打开了正确的聊天（失败自动从第二步重试，最多3次）→ 发送消息
- **第六步**：wechat-cli 确认消息到达

### 其他命令

```bash
# 只查联系人
python3 ~/.claude/skills/lucifer-wechat-skill/wechat_send.py --target "名字" --lookup-only

# 只打开聊天不发送
python3 ~/.claude/skills/lucifer-wechat-skill/wechat_send.py --target "名字" --dry-run

# 跳过预查
python3 ~/.claude/skills/lucifer-wechat-skill/wechat_send.py --target "名字" --message "内容" --skip-lookup
```

### 错误码

| 错误码 | 含义 |
|--------|------|
| CONTACT_NOT_FOUND | wechat-cli 未找到联系人或群聊 |
| CONTACT_FUZZY | 未精确匹配，有近似结果 |
| CONTACT_AMBIGUOUS | 多个精确匹配，需用户选择 |
| WECHAT_NOT_RUNNING | 微信未启动 |
| WECHAT_NOT_ACTIVATED | 找不到微信窗口 |
| NO_RESULT | 搜索 popup 中未找到目标 |
| WRONG_CHAT | OCR 验证失败，打开了错误的聊天 |

### 注意事项

- 发送期间不要操作鼠标键盘（脚本控制 GUI）
- 脚本会临时使用剪贴板，完成后自动恢复
- 内置 caffeinate 唤醒屏幕，防止锁屏导致失败
