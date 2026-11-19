#!/usr/bin/env python3
"""汇芯 Antigravity 中文界面安全切换器。

默认只检查，不修改应用。安装模式会先备份 app.asar，再使用 Electron 的
app 目录加载方式注入可回滚的 DOM 翻译层。它不会读取账号、对话或网络凭据。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


APP = Path("/Applications/Antigravity.app")
RESOURCES = APP / "Contents" / "Resources"
ASAR = RESOURCES / "app.asar"
DISABLED_ASAR = RESOURCES / "app.asar.disabled"
BACKUP = Path.home() / "Library" / "Application Support" / "huixin-antigravity-zh" / "app.asar.huixin-backup"
UNPACKED = RESOURCES / "app"
MARKER = "Huixin Antigravity Chinese Localization"
MENU_MARKER = f"{MARKER} Native Menu"
MIN_SUPPORTED = (2, 21, 1)

SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "huixin-antigravity-zh"
GUARD_SCRIPT = SUPPORT_DIR / "antigravity_zh_switcher.py"
GUARD_APP = SUPPORT_DIR / "HuixinZhGuard.app"
GUARD_BIN = GUARD_APP / "Contents" / "MacOS" / "HuixinZhGuard"
GUARD_STATE = SUPPORT_DIR / "guard_state.json"
GUARD_LOG = SUPPORT_DIR / "guard.log"
LAUNCH_AGENT_LABEL = "com.huixin.antigravity-zh-guard"
LAUNCH_AGENT_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"

TRANSLATIONS = {
    "Settings": "设置", "General": "常规", "Appearance": "外观", "Application": "应用",
    "Shortcuts": "快捷键", "Notifications": "通知", "Models": "模型", "Browser": "浏览器",
    "Customizations": "自定义", "Projects": "项目", "Conversations": "对话",
    "New Conversation": "新建对话", "Create New Project": "创建新项目", "No conversations yet": "暂无对话",
    "No Project": "未选择项目", "No project": "未选择项目",
    "Search Conversations": "搜索对话", "Display Options": "显示选项", "Project options": "项目选项",
    "Automations": "自动化", "Scheduled Tasks": "计划任务", "Provide Feedback": "提供反馈",
    "Welcome back,": "欢迎回来，", "Where should we pick up?": "我们要从哪里继续？",
    "what should we build today?": "今天想做点什么？", "Hey": "嗨",
    "Open Settings": "打开设置", "Close": "关闭", "Save": "保存", "Cancel": "取消",
    "Apply": "应用", "Reset": "重置", "Advanced": "高级", "Language": "语言",
    "Theme": "主题", "System": "系统", "Light": "浅色", "Dark": "深色",
    "Font": "字体", "Font Size": "字体大小", "Volume": "音量", "Microphone": "麦克风",
    "Interface Layout": "界面布局", "Knowledge Work": "知识工作", "Software Engineering": "软件开发",
    "Permissions": "权限", "Execution": "执行", "Voice mode": "语音模式", "Remote Control": "远程控制",
    "This Computer": "此电脑", "Remote": "远程", "Default": "默认", "Turbo": "高速",
    "Local permissions": "本地权限", "Local Permissions": "本地权限", "Request Review": "请求审阅",
    "Every command requires approval.": "每条命令都需要批准。",
    "Ask before sensitive operations.": "敏感操作前询问。",
    "Auto": "自动", "Automatically decide if commands run.": "自动决定是否运行命令。",
    "Run all commands without restrictions.": "不受限制地运行所有命令。",
    "Prevent Sleep": "防止睡眠", "Keep In Menu Bar": "保留在菜单栏", "Enable Remote Control": "启用远程控制",
    "Queued Messages": "排队消息", "Interrupt the agent and send immediately.": "中断智能体并立即发送。",
    "Queue until after the current turn.": "等当前轮次结束后再发送。",
    "Ask anything, @ to mention, / for actions": "输入问题，使用 @ 提及，使用 / 执行操作",
    "Message input": "消息输入框", "Add context": "添加上下文", "Select model": "选择模型",
    "Record voice memo": "录制语音备忘", "Start Voice mode": "开始语音模式", "Toggle Sidebar": "切换侧边栏",
    "Toggle Side Panel": "切换侧面板", "More actions": "更多操作", "More options": "更多选项",
    "Copy": "复制", "Undo to this point": "撤销到此处", "Good response": "回答得不错",
    "Bad response": "回答需要改进", "Worked for": "运行耗时", "now": "刚刚", "just now": "刚刚",
    "Conversation Log": "对话记录", "You said": "你说", "Agent said": "智能体说",
    "Agent working": "智能体工作中", "Waiting for user input": "等待你的输入",
    "Load older messages": "加载更早消息", "No more older messages": "没有更早消息",
    "Analyzing": "正在分析", "Turn": "轮次", "of": "共",
    "Loading": "正在加载", "Loading Antigravity": "正在加载 Antigravity", "Error": "错误",
    "Success": "成功", "Failed": "失败", "Running": "运行中", "Completed": "已完成",
    "File": "文件", "Edit": "编辑", "View": "视图", "Window": "窗口", "Help": "帮助",
    "New Window": "新建窗口", "Quit": "退出", "Check for Updates": "检查更新",
}

CONVERSATION_TITLES = {
    "Gemini Hydrogen Promo Video Creation": "Gemini Hydrogen 宣传视频制作",
    "Redesigning Company Official Website": "公司官网改版设计",
    "Local Video Promotional Style Review": "本地视频宣传风格评审",
    "Language Setting Location": "语言设置位置",
}


def version_tuple(value: str) -> tuple[int, int, int]:
    parts = (value.split(".") + ["0", "0", "0"])[:3]
    out = []
    for part in parts:
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out)  # type: ignore[return-value]


def app_version() -> str:
    with (APP / "Contents" / "Info.plist").open("rb") as handle:
        info = plistlib.load(handle)
    return str(info.get("CFBundleShortVersionString", "unknown"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_asar_tree(path: Path) -> dict:
    with path.open("rb") as handle:
        header = handle.read(16)
        if len(header) != 16:
            raise RuntimeError("app.asar 文件头不完整")
        _, size, _, header_size = struct.unpack("<4I", header)
        raw = handle.read(header_size)
    return json.loads(raw.decode("utf-8")).get("files", {})


def list_paths(tree: dict, prefix: str = "") -> list[str]:
    result: list[str] = []
    for name, info in tree.items():
        current = f"{prefix}/{name}" if prefix else name
        if "files" in info:
            result.extend(list_paths(info["files"], current))
        else:
            result.append(current)
    return result


def extract_asar(path: Path, destination: Path) -> None:
    with path.open("rb") as handle:
        _, size, _, header_size = struct.unpack("<4I", handle.read(16))
        tree = json.loads(handle.read(header_size).decode("utf-8")).get("files", {})
        base_offset = 8 + size
        unpacked_root = path.parent / "app.asar.unpacked"

        def visit(nodes: dict, folder: Path, relative: Path) -> None:
            folder.mkdir(parents=True, exist_ok=True)
            for name, info in nodes.items():
                target = folder / name
                relative_target = relative / name
                if "files" in info:
                    visit(info["files"], target, relative_target)
                elif info.get("unpacked"):
                    source = unpacked_root / relative_target
                    if not source.exists():
                        raise RuntimeError(f"找不到 app.asar.unpacked 文件：{source}")
                    if source.is_file():
                        shutil.copy2(source, target)
                else:
                    handle.seek(base_offset + int(info["offset"]))
                    target.write_bytes(handle.read(int(info["size"])))

        visit(tree, destination, Path())


def js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def make_injection() -> str:
    dictionary = json.dumps(TRANSLATIONS, ensure_ascii=False, separators=(",", ":"))
    title_dictionary = json.dumps(CONVERSATION_TITLES, ensure_ascii=False, separators=(",", ":"))
    return f"""
/* {MARKER} */
(function () {{
  const DICT = {dictionary};
  const TITLE_DICT = {title_dictionary};
  const SKIP = new Set(['INPUT','TEXTAREA','PRE','CODE','SCRIPT','STYLE']);
  const translate = (text) => {{
    if (!text || !text.trim()) return text;
    let value = text;
    Object.keys(DICT).sort((a,b) => b.length - a.length).forEach((key) => {{
      value = value.split(key).join(DICT[key]);
    }});
    return value;
  }};
  const replaceTitleText = (node, title, replacement) => {{
    Array.from(node.childNodes || []).forEach((child) => {{
      if (child.nodeType === 3) {{
        child.nodeValue = child.nodeValue.replace(title, replacement);
      }} else if (child.nodeType === 1) {{
        replaceTitleText(child, title, replacement);
      }}
    }});
  }};
  const visit = (node) => {{
    if (!node || (node.nodeType === 1 && SKIP.has(node.tagName))) return;
    if (node.nodeType === 3) {{
      const raw = node.nodeValue || '';
      const exactTitle = TITLE_DICT[raw.trim()];
      const next = exactTitle ? raw.replace(raw.trim(), exactTitle) :
        (raw.trim() === 'Local' ? raw.replace('Local', '本地') : translate(raw));
      if (next !== node.nodeValue) node.nodeValue = next;
      return;
    }}
    if (node.nodeType !== 1) return;
    const conversationLink = (node.tagName === 'A' || node.getAttribute('role') === 'link') &&
      /\/c\//.test(node.getAttribute('href') || node.getAttribute('data-href') || '');
    if (conversationLink) {{
      const fullTitle = (node.textContent || '').trim();
      const title = Object.keys(TITLE_DICT).find((key) => fullTitle.includes(key));
      if (title) {{
        replaceTitleText(node, title, TITLE_DICT[title]);
        node.setAttribute('aria-label', TITLE_DICT[title]);
      }}
      return;
    }}
    if (node.closest && node.closest('a[href*="/c/"]')) return;
    ['placeholder','title','aria-label'].forEach((name) => {{
      if (node.hasAttribute && node.hasAttribute(name)) {{
        const oldValue = node.getAttribute(name);
        const nextValue = translate(oldValue);
        if (nextValue !== oldValue) node.setAttribute(name, nextValue);
      }}
    }});
    node.childNodes && Array.from(node.childNodes).forEach(visit);
  }};
  const start = () => {{
    if (!document.body || !document.documentElement) {{
      setTimeout(start, 0);
      return;
    }}
    visit(document.body);
    new MutationObserver((records) => records.forEach((record) => record.addedNodes.forEach(visit))).observe(document.documentElement, {{childList:true,subtree:true}});
  }};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {{once:true}}); else start();
}})();
"""


def inject(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if MARKER in text:
        return True
    path.write_text(text.rstrip() + "\n" + make_injection(), encoding="utf-8")
    return True


def inject_native_menu(path: Path) -> bool:
    """Wrap Electron's application menu setter so macOS menu labels are Chinese too."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if MENU_MARKER in text:
        return True
    dictionary = json.dumps(TRANSLATIONS, ensure_ascii=False, separators=(",", ":"))
    wrapper = f"""
/* {MENU_MARKER} */
(function () {{
  const DICT = {dictionary};
  const translate = (value) => {{
    if (!value || !value.trim()) return value;
    let result = value;
    Object.keys(DICT).sort((a,b) => b.length - a.length).forEach((key) => {{
      result = result.split(key).join(DICT[key]);
    }});
    return result;
  }};
  const walk = (menu) => {{
    if (!menu || !menu.items) return;
    menu.items.forEach((item) => {{
      if (item.label) item.label = translate(item.label);
      if (item.submenu) walk(item.submenu);
    }});
  }};
  try {{
    const electron = require('electron');
    const original = electron.Menu.setApplicationMenu;
    electron.Menu.setApplicationMenu = function (menu) {{
      walk(menu);
      return original.call(this, menu);
    }};
  }} catch (_) {{}}
}})();
"""
    path.write_text(text.rstrip() + "\n" + wrapper, encoding="utf-8")
    return True


def is_app_running() -> bool:
    return (
        subprocess.run(
            ["pgrep", "-f", "/Applications/Antigravity.app/Contents/MacOS/Antigravity"],
            stdout=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def notify(title: str, message: str) -> None:
    try:
        script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
        subprocess.run(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def log_guard(message: str) -> None:
    try:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with GUARD_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def load_guard_state() -> dict:
    if not GUARD_STATE.exists():
        return {}
    try:
        return json.loads(GUARD_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_guard_state(state: dict) -> None:
    try:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        GUARD_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def check(quiet: bool = False) -> int:
    if not quiet:
        print(f"Antigravity: {APP}")
    if not APP.exists() or not ASAR.exists():
        if not quiet:
            print("结果：未找到原始 app.asar")
        return 2
    current = app_version()
    paths = set(list_paths(read_asar_tree(ASAR)))
    candidates = sorted(path for path in paths if path.endswith("preload.js") or path.endswith("menu.js"))
    required = {"dist/preload.js", "dist/menu.js"}
    supported = version_tuple(current) >= MIN_SUPPORTED and required.issubset(paths)
    if not quiet:
        print(f"版本：{current}")
        print(f"架构：{os.uname().machine}")
        print(f"app.asar SHA-256：{sha256(ASAR)}")
        print("候选入口：")
        for path in candidates[:20]:
            print(f"  - {path}")
        print("结果：结构可识别，可以进入副本试运行" if supported else "结果：暂不支持自动安装")
        print("注意：这还不是安装；不会改动应用。")
    return 0 if supported else 1


def install(force: bool, quiet: bool = False) -> int:
    if check(quiet=quiet) != 0 and not force:
        if not quiet:
            print("未通过检查，未执行安装。需要明确使用 --force 才会继续。")
        return 1
    if not ASAR.exists():
        if not quiet:
            print("找不到 app.asar")
        return 2
    if is_app_running():
        if not quiet:
            print("请先完全退出 Antigravity，再运行 install。")
        return 1
    # 官方升级可能会覆盖出新的 app.asar，同时残留旧的 app/ 或 app.asar.disabled；安全清理后再重装
    if UNPACKED.exists():
        shutil.rmtree(UNPACKED)
    if DISABLED_ASAR.exists():
        DISABLED_ASAR.unlink()
    reuse_backup = False
    if BACKUP.exists():
        if sha256(BACKUP) == sha256(ASAR):
            reuse_backup = True
            if not quiet:
                print(f"复用未改变的原始备份：{BACKUP}")
        else:
            if not quiet:
                print(f"检测到官方版本已更新，刷新原始备份：{BACKUP}")
    with tempfile.TemporaryDirectory(prefix="antigravity-zh-") as temp:
        staging = Path(temp) / "app"
        extract_asar(ASAR, staging)
        preload = staging / "dist" / "preload.js"
        if not preload.exists():
            if not quiet:
                print("当前版本没有找到 dist/preload.js，已停止，未改动应用。")
            return 1
        inject(preload)
        menu = staging / "dist" / "menu.js"
        inject_native_menu(menu)
        # 保留解包目录，Electron 会在 app.asar.disabled 时加载它。
        if not reuse_backup:
            shutil.copy2(ASAR, BACKUP)
        shutil.copytree(staging, UNPACKED)
    ASAR.rename(DISABLED_ASAR)
    if not quiet:
        print("安装完成。请启动 Antigravity 检查界面；还原命令：restore")
    return 0


def restore() -> int:
    if not BACKUP.exists():
        print("没有找到汇芯备份，未执行还原。")
        return 1
    if is_app_running():
        print("请先完全退出 Antigravity，再运行 restore。")
        return 1
    if ASAR.exists():
        ASAR.unlink()
    if DISABLED_ASAR.exists():
        DISABLED_ASAR.unlink()
    shutil.copy2(BACKUP, ASAR)
    if UNPACKED.exists():
        shutil.rmtree(UNPACKED)
    print("已恢复官方英文版；备份仍保留在：", BACKUP)
    return 0


def is_localized() -> bool:
    preload = UNPACKED / "dist" / "preload.js"
    return UNPACKED.exists() and DISABLED_ASAR.exists() and not ASAR.exists() and preload.exists()


def auto_sync() -> int:
    """供 LaunchAgent 调用：检测到官方升级导致汉化丢失时自动重新注入。"""
    if not APP.exists():
        return 0
    if is_localized():
        return 0
    if not ASAR.exists():
        return 0

    current = app_version()
    if check(quiet=True) != 0:
        state = load_guard_state()
        if state.get("incompatible_notified") != current:
            log_guard(f"检测到 Antigravity {current} 结构不兼容，已跳过自动汉化")
            notify("汇芯 Antigravity 汉化守护", f"检测到新版本 {current} 结构有变化，暂未自动汉化，请检查工具更新。")
            state["incompatible_notified"] = current
            save_guard_state(state)
        return 1

    if is_app_running():
        state = load_guard_state()
        if state.get("pending_notified") != current:
            log_guard(f"检测到 Antigravity {current} 汉化已失效（升级覆盖），等待用户退出后自动恢复")
            notify("汇芯 Antigravity 汉化守护", f"检测到已升级到 {current}，完全退出应用后将自动恢复中文界面。")
            state["pending_notified"] = current
            save_guard_state(state)
        return 0

    try:
        code = install(force=False, quiet=True)
    except PermissionError as exc:
        state = load_guard_state()
        if state.get("permission_notified") != current:
            log_guard(f"Antigravity {current} 自动汉化缺少 App 管理权限：{exc}")
            notify("汇芯 Antigravity 汉化守护", "请在系统设置 → 隐私与安全性 → App 管理中允许 HuixinZhGuard.app 修改应用。")
            state["permission_notified"] = current
            save_guard_state(state)
        return 1
    if code == 0:
        log_guard(f"已自动为 Antigravity {current} 重新注入中文界面")
        notify("汇芯 Antigravity 汉化守护", f"Antigravity {current} 中文界面已自动同步完成。")
        state = load_guard_state()
        state["last_synced_version"] = current
        state.pop("pending_notified", None)
        state.pop("permission_notified", None)
        save_guard_state(state)
    else:
        log_guard(f"Antigravity {current} 自动汉化失败，退出码：{code}")
    return code


def ensure_guard_app() -> bool:
    """在首次启用守护时生成静默 .app 包装器，便于在 macOS「App 管理」中持久授权。"""
    if GUARD_BIN.exists():
        return True
    clang = shutil.which("clang")
    codesign = shutil.which("codesign")
    if not clang or not codesign:
        return False
    macos_dir = GUARD_APP / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True, exist_ok=True)
    plist_data = {
        "CFBundleDevelopmentRegion": "zh_CN",
        "CFBundleExecutable": "HuixinZhGuard",
        "CFBundleIdentifier": "com.huixin.antigravity-zh-guard-helper",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "HuixinZhGuard",
        "CFBundleDisplayName": "汇芯 Antigravity 汉化守护",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "LSBackgroundOnly": True,
        "LSUIElement": True,
    }
    with (GUARD_APP / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump(plist_data, handle)
    python_bin = shutil.which("python3") or sys.executable
    c_source = (
        "#include <unistd.h>\n"
        "int main(void) {\n"
        f'    char *argv[] = {{{json.dumps(python_bin)}, {json.dumps(str(GUARD_SCRIPT))}, "auto-sync", NULL}};\n'
        f"    execv({json.dumps(python_bin)}, argv);\n"
        "    return 127;\n"
        "}\n"
    )
    with tempfile.TemporaryDirectory(prefix="huixin-guard-build-") as temp:
        src = Path(temp) / "guard.c"
        src.write_text(c_source, encoding="utf-8")
        res = subprocess.run([clang, "-O2", "-Wall", "-Wextra", str(src), "-o", str(GUARD_BIN)], capture_output=True)
        if res.returncode != 0:
            return False
    sign_res = subprocess.run(
        [codesign, "--force", "--deep", "--sign", "-", "--identifier", "com.huixin.antigravity-zh-guard-helper", str(GUARD_APP)],
        capture_output=True,
    )
    return sign_res.returncode == 0


def guard_enable() -> int:
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).resolve(), GUARD_SCRIPT)
    GUARD_SCRIPT.chmod(0o755)
    has_guard_app = ensure_guard_app()
    LAUNCH_AGENT_PLIST.parent.mkdir(parents=True, exist_ok=True)
    program_args = [str(GUARD_BIN)] if has_guard_app and GUARD_BIN.exists() else [sys.executable, str(GUARD_SCRIPT), "auto-sync"]
    plist_data = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": program_args,
        "WatchPaths": [str(RESOURCES), str(APP / "Contents" / "Info.plist")],
        "StartInterval": 15,
        "RunAtLoad": True,
        "StandardOutPath": str(GUARD_LOG),
        "StandardErrorPath": str(GUARD_LOG),
    }
    with LAUNCH_AGENT_PLIST.open("wb") as handle:
        plistlib.dump(plist_data, handle)
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LAUNCH_AGENT_LABEL}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    res = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(LAUNCH_AGENT_PLIST)], capture_output=True, text=True)
    if res.returncode != 0:
        # 兼容旧版 macOS launchctl load
        subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT_PLIST)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["launchctl", "load", str(LAUNCH_AGENT_PLIST)], check=False)
    log_guard("已启用升级自动保持汉化守护服务")
    print(f"已开启升级自动保持汉化守护：{LAUNCH_AGENT_PLIST}")
    print(f"守护脚本副本：{GUARD_SCRIPT}")
    if GUARD_APP.exists():
        print(f"授权应用壳：{GUARD_APP}")
        print("首次使用请在「系统设置 → 隐私与安全性 → App 管理」中添加并允许 HuixinZhGuard.app，之后永久自动生效。")
    print("以后每次 Antigravity 升级，只要退出应用，15 秒内会自动同步中文界面。")
    auto_sync()
    return 0


def guard_disable() -> int:
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LAUNCH_AGENT_LABEL}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT_PLIST)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if LAUNCH_AGENT_PLIST.exists():
        LAUNCH_AGENT_PLIST.unlink()
    log_guard("已停用升级自动保持汉化守护服务")
    print("已关闭升级自动保持汉化守护。")
    return 0


def guard_status() -> int:
    print(f"Antigravity 版本：{app_version() if APP.exists() else '未安装'}")
    print(f"当前界面状态：{'已汉化（生效中）' if is_localized() else '未汉化（官方英文版或刚升级）'}")
    print(f"应用运行状态：{'运行中' if is_app_running() else '未运行'}")
    print(f"自动守护配置：{'已启用' if LAUNCH_AGENT_PLIST.exists() else '未启用'}")
    if LAUNCH_AGENT_PLIST.exists():
        print(f"Plist 路径：{LAUNCH_AGENT_PLIST}")
    if GUARD_LOG.exists():
        lines = GUARD_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()[-5:]
        if lines:
            print("最近守护日志：")
            for line in lines:
                print(f"  {line}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="汇芯 Antigravity 中文界面安全切换器")
    parser.add_argument(
        "command",
        choices=["check", "install", "restore", "auto-sync", "guard-enable", "guard-disable", "guard-status"],
    )
    parser.add_argument("--force", action="store_true", help="跳过版本检查；仅在确认兼容时使用")
    args = parser.parse_args()
    if args.command == "check":
        return check()
    if args.command == "install":
        return install(args.force)
    if args.command == "restore":
        return restore()
    if args.command == "auto-sync":
        return auto_sync()
    if args.command == "guard-enable":
        return guard_enable()
    if args.command == "guard-disable":
        return guard_disable()
    return guard_status()


if __name__ == "__main__":
    raise SystemExit(main())
