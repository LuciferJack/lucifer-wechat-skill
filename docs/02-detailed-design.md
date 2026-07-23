# 详设文档: macOS 微信消息发送 Skill v2.0

## 0. 技术约束（调研结论）

| 路线 | 可行性 | 原因 |
|------|--------|------|
| Accessibility API (AXUIElement) | ❌ 不可行 | 微信 4.1.11 基于 Chromium 渲染，AX 树只暴露窗口框架（3个按钮），内部 UI 元素完全不可访问 |
| Chrome DevTools Protocol | ❌ 不可行 | 微信本地端口 (14013-14023) 是 mojo IPC，不支持 CDP HTTP 协议 |
| AppleScript 原生字典 | ❌ 不可行 | 微信无 sdef 文件，不支持 AppleScript 原生命令 |
| weixin:// URL Scheme | ⚠️ 有限 | 注册了 xweixin/weixin/wechat scheme，但无公开的 `chat?wxid=` 打开聊天的深度链接 |
| AppleScript 键盘模拟 | ✅ 唯一可行 | 通过 System Events 发送键盘事件 |
| screencapture + macOS Vision OCR | ✅ 可行 | 用于验证当前聊天窗口标题 |
| wechat-cli | ✅ 可行 | 读取本地数据库，用于联系人查询和发送后验证 |

**结论：只能走 AppleScript 键盘模拟 + OCR 验证路线，重点是修复旧方案的两个 bug。**

## 1. 旧方案失败根因

### Bug 1: 搜索后 Enter×2 触发"搜一搜"

旧流程：`Cmd+F → 粘贴 → Enter → Enter`

在微信 4.x 中，第一个 Enter 提交搜索到"搜一搜"网页，而非在本地搜索结果中选择联系人。

**修复**：不用 Enter 提交搜索。粘贴后等待本地下拉结果出现，用 `Down` 键导航到第一个联系人结果，再 `Enter` 选中。

### Bug 2: 截图验证依赖 AI 识图

旧方案用 `screencapture` + Claude 读图来验证目标。这需要 AI 参与，增加延迟和不确定性。

**修复**：用 macOS 原生 Vision 框架做 OCR，程序化读取截图中的聊天标题文字，精确匹配。

## 2. 架构

```
wechat_send.py (独立 Python 脚本，~200 行)
│
├── activate_wechat()        # 激活微信 + 防锁屏
├── open_chat(target)        # 多策略打开目标聊天
│   ├── try_session_click()  # 策略1: Esc 回主界面，Cmd+F 搜索，Down+Enter 选中
│   └── verify_chat()        # OCR 验证当前聊天标题
├── send_message(text)       # 定位输入框 + 粘贴 + 发送
└── main()                   # CLI 入口
```

## 3. 接口定义

### 3.1 CLI 接口

```bash
python3 wechat_send.py \
    --target "文件传输助手" \
    --message "你好" \
    [--dry-run]              # 只打开聊天，不发送
    [--verify-only]          # 只验证当前聊天标题
    [--timeout 15]           # 总超时秒数，默认 15
```

### 3.2 输出格式

```json
// 成功
{"status": "sent", "target": "文件传输助手", "message": "你好"}

// 失败
{"status": "error", "code": "WRONG_CHAT", "detail": "期望: 文件传输助手, 实际: 莫靖杰"}

// dry-run
{"status": "ready", "target": "文件传输助手", "verified": true}
```

### 3.3 错误码

| 错误码 | 含义 | 用户操作建议 |
|--------|------|-------------|
| WECHAT_NOT_RUNNING | 微信未启动 | 启动微信并登录 |
| WECHAT_NOT_ACTIVATED | 微信无法激活到前台 | 检查窗口是否最小化到 Dock |
| SEARCH_TIMEOUT | 搜索超时，未出现下拉结果 | 检查微信是否卡住 |
| NO_RESULT | 搜索无匹配结果 | 检查联系人/群名是否正确 |
| WRONG_CHAT | OCR 验证失败，打开了错误的聊天 | 手动确认后重试 |
| SEND_FAILED | 消息发送失败 | 检查微信输入框是否可用 |
| OCR_FAILED | OCR 识别失败 | 检查屏幕分辨率/缩放设置 |

## 4. 核心流程

### 4.1 打开聊天 (`open_chat`)

```
activate_wechat()
    │
    ▼
Esc (关闭可能的弹窗/搜一搜页面)
    │
    ▼
Cmd+F (聚焦搜索框)
    │
    ▼
Cmd+A (清空搜索框)
    │
    ▼
粘贴 target (通过剪贴板 Cmd+V)
    │
    ▼
等待 1.5s (等本地搜索结果下拉出现)
    │
    ▼
Down 键 (选中第一个本地结果，跳过"搜一搜"入口)
    │
    ▼
Enter (打开选中的聊天)
    │
    ▼
等待 1.5s (等聊天窗口加载)
    │
    ▼
截图 + OCR 验证聊天标题
    │
    ├─ 标题匹配 → 继续发送
    └─ 标题不匹配 → 返回 WRONG_CHAT 错误
```

### 4.2 发送消息 (`send_message`)

```
Option+Down (跳到聊天底部)
    │
    ▼
Option+Up (定位到输入框)
    │
    ▼
粘贴消息文本 (剪贴板 Cmd+V)
    │
    ▼
Enter (发送)
    │
    ▼
wechat-cli history 验证发送成功
```

### 4.3 OCR 验证 (`verify_chat`)

```python
# 使用 macOS Vision 框架
import Vision, Quartz

def ocr_region(image_path, region):
    """对截图指定区域做 OCR，返回识别文字"""
    image = Quartz.CGImageCreateWithImageInRect(full_image, region)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLanguages_(["zh-Hans", "en"])
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
    handler.performRequests_error_([request], None)
    return [obs.topCandidates_(1)[0].string() for obs in request.results()]
```

验证逻辑：
- 截取微信窗口聊天区域顶部（聊天标题位置）
- OCR 提取文字
- 用模糊匹配（包含关系）验证是否是目标联系人/群名
- 群名允许忽略尾部 `(数字)` 后缀

## 5. 关键设计决策

### 5.1 为什么 Down×1 而不是 Down×N？

微信搜索下拉的第一项就是最匹配的本地联系人/群聊（如果存在），"搜一搜"入口在最底部或最顶部。Down×1 跳过顶部的"搜一搜"建议，直接到第一个本地结果。

如果 Down×1 不对（OCR 验证会发现），脚本返回 WRONG_CHAT 错误，用户可以调整。不盲发。

### 5.2 为什么用 Vision OCR 而不是截图+AI？

- Vision 是 macOS 原生框架，Python 可直接调用，零依赖
- 延迟 < 200ms，比 AI 识图快 10 倍以上
- 纯程序化判断，无不确定性
- 中文识别精度高（Apple 的中文 OCR 模型）

### 5.3 为什么不做会话列表直接点击？

AX API 不可用 → 无法通过 identifier 找到会话列表元素 → 无法程序化点击。用坐标点击需要知道联系人在列表中的精确位置，不可靠。统一走搜索流程更简单。

### 5.4 剪贴板保存/恢复

发送消息需要用剪贴板粘贴（中文支持），会覆盖用户剪贴板。流程：
1. 保存当前剪贴板内容
2. 设置剪贴板为 target/message
3. 粘贴
4. 恢复剪贴板

## 6. SKILL.md 变更

只替换"能力一：发送消息"部分：
- 删除模式 A / 模式 B 的 AppleScript 代码模板
- 替换为调用 `wechat_send.py` 脚本
- 保留所有安全规则和确认规则
- 保留"能力二：查看消息"不变

## 7. 文件清单

| 文件 | 说明 |
|------|------|
| `~/.claude/skills/wechat-mac/wechat_send.py` | 核心发送脚本 |
| `~/.claude/skills/wechat-mac/SKILL.md` | 更新的 Skill 文档 |

## 8. 测试计划

| 用例 | 输入 | 期望结果 |
|------|------|----------|
| 发送给文件传输助手 | `--target "文件传输助手" --message "test"` | 成功发送 |
| 发送给不存在的联系人 | `--target "不存在的人" --message "test"` | NO_RESULT 错误 |
| dry-run 模式 | `--target "文件传输助手" --dry-run` | 打开聊天，不发送 |
| 微信未启动 | 关闭微信后运行 | WECHAT_NOT_RUNNING 错误 |
| 验证当前聊天 | `--verify-only` | 返回当前聊天标题 |
| 中文特殊字符消息 | `--message "测试"引号"和emoji😊"` | 成功发送，内容无损 |
