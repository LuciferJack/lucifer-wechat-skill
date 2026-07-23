#!/usr/bin/env python3
"""macOS WeChat message sender: AppleScript keyboard automation + Vision OCR verification."""

import argparse
import json
import os
import re
import subprocess
import sys
import time

import AppKit
import objc
from Foundation import NSBundle, NSURL
import Quartz

_vision_bundle = NSBundle.bundleWithPath_("/System/Library/Frameworks/Vision.framework")
_vision_bundle.load()
VNRecognizeTextRequest = objc.lookUpClass("VNRecognizeTextRequest")
VNImageRequestHandler = objc.lookUpClass("VNImageRequestHandler")

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
WECHAT_CLI = os.path.join(SKILL_DIR, "bin", "wechat-cli")
SCREENSHOT_PATH = "/tmp/wechat_send_v2_verify.png"
RETINA_SCALE = 2


def output(status, **kwargs):
    print(json.dumps({"status": status, **kwargs}, ensure_ascii=False))
    sys.stdout.flush()


def run_applescript(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"AppleScript error: {r.stderr.strip()}")
    return r.stdout.strip()


def set_clipboard(text):
    pb = AppKit.NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, AppKit.NSPasteboardTypeString)


def get_clipboard():
    pb = AppKit.NSPasteboard.generalPasteboard()
    return pb.stringForType_(AppKit.NSPasteboardTypeString)


def get_wechat_window():
    """Return (x, y, w, h) of the main WeChat window, or None."""
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    best, best_area = None, 0
    for w in windows:
        if w.get("kCGWindowOwnerName") != "微信":
            continue
        name = w.get("kCGWindowName", "")
        if not name or not name.startswith("微信"):
            continue
        b = w["kCGWindowBounds"]
        area = b["Width"] * b["Height"]
        if area > best_area:
            best = (b["X"], b["Y"], b["Width"], b["Height"])
            best_area = area
    return best


def ocr_region(image_path, region=None):
    """OCR a screenshot, optionally cropped to region (x, y, w, h) in screen coords.
    Returns list of (text, screen_x, screen_y, screen_w, screen_h)."""
    url = NSURL.fileURLWithPath_(image_path)
    source = Quartz.CGImageSourceCreateWithURL(url, None)
    if not source:
        return []
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if not image:
        return []

    img_w = Quartz.CGImageGetWidth(image)
    img_h = Quartz.CGImageGetHeight(image)

    if region:
        rx, ry, rw, rh = region
        crop_rect = Quartz.CGRectMake(
            rx * RETINA_SCALE, ry * RETINA_SCALE,
            rw * RETINA_SCALE, rh * RETINA_SCALE
        )
        image = Quartz.CGImageCreateWithImageInRect(image, crop_rect)
        if not image:
            return []
        img_w = Quartz.CGImageGetWidth(image)
        img_h = Quartz.CGImageGetHeight(image)

    request = VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLanguages_(["zh-Hans", "en"])
    handler = VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
    handler.performRequests_error_([request], objc.nil)

    results = []
    for obs in (request.results() or []):
        cands = obs.topCandidates_(1)
        if not cands:
            continue
        text = cands[0].string()
        bb = obs.boundingBox()
        px = bb.origin.x * img_w
        py = (1 - bb.origin.y - bb.size.height) * img_h
        pw = bb.size.width * img_w
        ph = bb.size.height * img_h
        sx = px / RETINA_SCALE
        sy = py / RETINA_SCALE
        sw = pw / RETINA_SCALE
        sh = ph / RETINA_SCALE
        if region:
            sx += region[0]
            sy += region[1]
        results.append((text, sx, sy, sw, sh))
    return results


def click_at(x, y):
    p = Quartz.CGPoint(x, y)
    d = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, p, 0)
    u = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, p, 0)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, d)
    time.sleep(0.05)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, u)


def normalize(name):
    """Normalize contact/group name: strip trailing (N) suffix and whitespace."""
    return re.sub(r"\s*[\(（]\d+[\)）]$", "", name.strip()).strip()


def lookup_contact(target):
    """Pre-check if target exists via wechat-cli. Returns dict with match info.

    Returns:
        {"found": True, "exact": True, "name": "...", "type": "contact|group"}
        {"found": True, "exact": False, "suggestions": [...]}
        {"found": False, "suggestions": []}
    """
    target_norm = normalize(target)
    exact_matches = []
    fuzzy_matches = []

    # 1. Search contacts (individual + public accounts)
    try:
        r = subprocess.run(
            [WECHAT_CLI, "contacts", "--query", target, "--format", "json"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            contacts = json.loads(r.stdout)
            for c in contacts:
                display = c.get("remark") or c.get("nick_name", "")
                nick = c.get("nick_name", "")
                display_norm = normalize(display)
                nick_norm = normalize(nick)
                uname = c.get("username", "")
                ctype = "group" if "@chatroom" in uname else "contact"
                entry = {"name": display or nick, "nick_name": nick,
                         "type": ctype, "username": uname}
                if display_norm == target_norm or nick_norm == target_norm:
                    exact_matches.append(entry)
                else:
                    fuzzy_matches.append(entry)
    except Exception:
        pass

    # 2. Search sessions (includes group chats)
    try:
        r = subprocess.run(
            [WECHAT_CLI, "sessions", "--limit", "500", "--format", "json"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            sessions = json.loads(r.stdout)
            for s in sessions:
                chat_name = s.get("chat", "")
                chat_norm = normalize(chat_name)
                is_group = s.get("is_group", False)
                entry = {"name": chat_name, "type": "group" if is_group else "contact",
                         "username": s.get("username", "")}
                if chat_norm == target_norm:
                    if not any(m["username"] == entry["username"] for m in exact_matches):
                        exact_matches.append(entry)
                elif target_norm in chat_norm or chat_norm in target_norm:
                    if not any(m["username"] == entry["username"] for m in fuzzy_matches):
                        fuzzy_matches.append(entry)
    except Exception:
        pass

    if exact_matches:
        m = exact_matches[0]
        return {"found": True, "exact": True, "name": m["name"],
                "type": m["type"], "all_exact": exact_matches}

    if fuzzy_matches:
        suggestions = [{"name": m["name"], "type": m["type"]} for m in fuzzy_matches[:10]]
        return {"found": True, "exact": False, "suggestions": suggestions}

    return {"found": False, "suggestions": []}


def activate_wechat():
    """Activate WeChat and bring to front. Returns True on success."""
    apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(
        "com.tencent.xinWeChat"
    )
    if not apps:
        output("error", code="WECHAT_NOT_RUNNING", detail="微信未启动")
        return False

    subprocess.run(["caffeinate", "-u", "-t", "2"], timeout=5)
    time.sleep(0.5)

    apps[0].activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
    time.sleep(0.5)

    run_applescript('''
tell application "System Events"
    tell process "WeChat"
        set frontmost to true
    end tell
end tell
''')
    time.sleep(0.5)

    if not get_wechat_window():
        subprocess.run(["open", "-a", "WeChat"], timeout=5)
        time.sleep(2)
        run_applescript('''
tell application "System Events"
    tell process "WeChat"
        set frontmost to true
    end tell
end tell
''')
        time.sleep(0.5)

    if not get_wechat_window():
        output("error", code="WECHAT_NOT_ACTIVATED", detail="找不到微信窗口")
        return False

    return True


def reset_state():
    """Press Esc to dismiss any search/popup state and return to main view."""
    run_applescript('''
tell application "System Events"
    tell process "WeChat"
        key code 53
        delay 0.3
        key code 53
        delay 0.3
    end tell
end tell
''')
    time.sleep(0.5)


def verify_chat(target, win):
    """OCR the chat title area and check if it matches target. Returns True/False."""
    subprocess.run(["screencapture", "-x", SCREENSHOT_PATH], check=True)

    wx, wy, ww, wh = win
    title_region = (wx + ww * 0.33, wy, ww * 0.5, 80)
    entries = ocr_region(SCREENSHOT_PATH, title_region)

    target_norm = normalize(target)
    for text, *_ in entries:
        text_norm = normalize(text)
        if target_norm == text_norm:
            return True
        if target_norm in text_norm or (text_norm in target_norm and len(text_norm) >= 2):
            return True
    return False


def locate_in_popup(target, win):
    """第三步：截图，OCR定位目标在popup中的屏幕坐标。返回 (x, y) 或 None。"""
    subprocess.run(["screencapture", "-x", SCREENSHOT_PATH], check=True)
    entries = ocr_region(SCREENSHOT_PATH)

    wx, wy, ww, wh = win
    sidebar_right = wx + ww * 0.35
    target_norm = normalize(target)

    section_headers = {}
    candidates = []
    for text, sx, sy, sw, sh in entries:
        if not (wx <= sx < sidebar_right and sy > wy + 40 and sy < wy + wh):
            continue
        stripped = text.strip()
        if stripped in ("联系人", "群聊", "功能", "搜索网络结果", "聊天记录", "搜一搜"):
            section_headers[stripped] = sy
            continue
        # Skip search suggestions (Q-prefixed)
        if text.strip().startswith("Q ") or text.strip().startswith("Q "):
            continue
        cleaned = re.sub(r'^[🔍口\s]+', '', text).rstrip("]").strip()
        cleaned_norm = normalize(cleaned)
        if cleaned_norm == target_norm:
            candidates.append((cleaned, sx, sy, sw, sh, True))
        elif target_norm in cleaned_norm or cleaned_norm in target_norm:
            if len(cleaned_norm) >= 2:
                candidates.append((cleaned, sx, sy, sw, sh, False))

    def get_section(entry_y):
        section, best_y = None, -1
        for name, hy in section_headers.items():
            if hy < entry_y and hy > best_y:
                section, best_y = name, hy
        return section

    # Pick best: 联系人/群聊 exact > 联系人/群聊 fuzzy > 功能 exact > 功能 fuzzy
    for exact_only in [True, False]:
        # Pass 1: 联系人/群聊
        for _, sx, sy, sw, sh, is_exact in candidates:
            if exact_only and not is_exact:
                continue
            section = get_section(sy)
            if section in ("联系人", "群聊"):
                return sx + sw / 2, sy + sh / 2
        # Pass 2: 功能 or no section (but not 搜一搜/搜索网络结果)
        for _, sx, sy, sw, sh, is_exact in candidates:
            if exact_only and not is_exact:
                continue
            section = get_section(sy)
            if section in ("搜一搜", "搜索网络结果"):
                continue
            return sx + sw / 2, sy + sh / 2

    return None


def type_in_search(target, win):
    """搜索框输入目标名，不点击，等2s让popup出现。"""
    wx, wy, ww, wh = win
    search_x = wx + ww * 0.2
    search_y = wy + 30
    click_at(search_x, search_y)
    time.sleep(0.8)

    set_clipboard(target)
    time.sleep(0.1)
    run_applescript('''
tell application "System Events"
    tell process "WeChat"
        keystroke "a" using {command down}
        delay 0.1
        keystroke "v" using {command down}
    end tell
end tell
''')
    time.sleep(2.0)
    return True


def open_chat(target, max_retries=3):
    """打开聊天（第二~五步），第五步失败自动重试整个流程：
    第二步：搜索框输入目标名，不点击，等2s，popup出现
    第三步：截图定位目标的屏幕坐标
    第四步：再次搜索框输入目标名，等2s，popup出现，点击坐标
    第五步：截图确认打开了正确的聊天（失败则从第二步重来）
    """
    for attempt in range(max_retries):
        reset_state()

        win = get_wechat_window()
        if not win:
            output("error", code="WECHAT_NOT_ACTIVATED", detail="找不到微信窗口")
            return False

        run_applescript('''
tell application "System Events"
    tell process "WeChat"
        set frontmost to true
    end tell
end tell
''')
        time.sleep(0.5)

        # 第二步：搜索框输入，不点击，等2s，popup出现
        type_in_search(target, win)

        # 第三步：截图定位目标的屏幕坐标
        pos = locate_in_popup(target, win)
        if not pos:
            reset_state()
            output("error", code="NO_RESULT",
                   detail=f"搜索 popup 中未找到: {target}")
            return False

        # 第四步：再次搜索框输入，等2s，popup出现，点击坐标
        reset_state()
        time.sleep(0.5)
        type_in_search(target, win)
        click_at(pos[0], pos[1])
        time.sleep(2.0)

        # 第五步：截图确认打开了正确的聊天
        win = get_wechat_window()
        if not win:
            output("error", code="WECHAT_NOT_ACTIVATED", detail="验证时找不到微信窗口")
            return False

        if verify_chat(target, win):
            return True

    output("error", code="WRONG_CHAT",
           detail=f"重试{max_retries}次仍未匹配到: {target}")
    return False


def send_message(text):
    """Paste message into input field and send."""
    run_applescript('''
tell application "System Events"
    tell process "WeChat"
        set frontmost to true
    end tell
end tell
''')
    time.sleep(0.3)

    set_clipboard(text)
    time.sleep(0.1)

    run_applescript('''
tell application "System Events"
    tell process "WeChat"
        keystroke "v" using {command down}
        delay 0.5
        key code 36
    end tell
end tell
''')
    time.sleep(0.5)


def verify_sent(target, message):
    """Use wechat-cli to check if message was sent."""
    try:
        r = subprocess.run(
            [WECHAT_CLI, "history", target, "--limit", "5", "--format", "text"],
            capture_output=True, text=True, timeout=10,
        )
        if message[:20] in r.stdout:
            return True
    except Exception:
        pass
    return False


def main():
    parser = argparse.ArgumentParser(description="WeChat message sender v2")
    parser.add_argument("--target", required=True, help="Contact or group name")
    parser.add_argument("--message", help="Message text to send")
    parser.add_argument("--dry-run", action="store_true", help="Open chat without sending")
    parser.add_argument("--verify-only", action="store_true", help="Only verify current chat title")
    parser.add_argument("--skip-lookup", action="store_true", help="Skip wechat-cli contact lookup")
    parser.add_argument("--lookup-only", action="store_true", help="Only lookup contact, don't send")
    args = parser.parse_args()

    if args.lookup_only:
        lookup = lookup_contact(args.target)
        if not lookup["found"]:
            output("error", code="CONTACT_NOT_FOUND",
                   detail=f"未找到联系人或群聊: {args.target}", suggestions=[])
        elif not lookup["exact"]:
            output("fuzzy_match", target=args.target,
                   suggestions=lookup["suggestions"])
        else:
            extra = {}
            if lookup.get("all_exact") and len(lookup["all_exact"]) > 1:
                extra["all_matches"] = [{"name": m["name"], "type": m["type"]}
                                        for m in lookup["all_exact"]]
            output("exact_match", target=args.target,
                   name=lookup["name"], type=lookup["type"], **extra)
        return

    if args.verify_only:
        win = get_wechat_window()
        if not win:
            output("error", code="WECHAT_NOT_ACTIVATED", detail="找不到微信窗口")
            return
        ok = verify_chat(args.target, win)
        output("verified" if ok else "error", target=args.target,
               **({"verified": True} if ok else {"code": "WRONG_CHAT",
                   "detail": f"当前聊天不是: {args.target}"}))
        return

    if not args.dry_run and not args.message:
        output("error", code="NO_MESSAGE", detail="--message is required")
        sys.exit(1)

    # Step 1: Pre-check contact/group existence via wechat-cli
    if not args.skip_lookup:
        lookup = lookup_contact(args.target)
        if not lookup["found"]:
            output("error", code="CONTACT_NOT_FOUND",
                   detail=f"未找到联系人或群聊: {args.target}",
                   suggestions=[])
            sys.exit(1)
        if not lookup["exact"]:
            output("error", code="CONTACT_FUZZY",
                   detail=f"未找到精确匹配: {args.target}，以下是近似结果",
                   suggestions=lookup["suggestions"])
            sys.exit(1)
        # Exact match found — use the matched name for sending
        matched_name = lookup["name"]
        if lookup.get("all_exact") and len(lookup["all_exact"]) > 1:
            output("error", code="CONTACT_AMBIGUOUS",
                   detail=f"找到多个匹配: {args.target}",
                   suggestions=[{"name": m["name"], "type": m["type"]}
                                for m in lookup["all_exact"]])
            sys.exit(1)
    else:
        matched_name = args.target

    # 第二~六步：一气呵成
    saved_clipboard = get_clipboard()
    try:
        if not activate_wechat():
            sys.exit(1)

        # 第二~五步：搜索定位 → 点击 → 截图确认聊天
        if not open_chat(matched_name):
            sys.exit(1)

        if args.dry_run:
            output("ready", target=matched_name, verified=True)
            return

        # 第五步续：发送消息
        send_message(args.message)
        time.sleep(1)

        # 第六步：wechat-cli 确认消息到达
        verified = verify_sent(matched_name, args.message)
        if verified:
            output("sent", target=matched_name, message=args.message, verified=True)
        else:
            output("sent", target=matched_name, message=args.message, verified=False,
                   warning="wechat-cli 未确认消息到达，请手动检查")
    finally:
        if saved_clipboard:
            set_clipboard(saved_clipboard)


if __name__ == "__main__":
    main()
