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
BACKUP = RESOURCES / "app.asar.huixin-backup"
UNPACKED = RESOURCES / "app"
MARKER = "Huixin Antigravity Chinese Localization"
MENU_MARKER = f"{MARKER} Native Menu"
MIN_SUPPORTED = (2, 21, 1)

TRANSLATIONS = {
    "Settings": "设置", "General": "常规", "Appearance": "外观", "Application": "应用",
    "Shortcuts": "快捷键", "Notifications": "通知", "Models": "模型", "Browser": "浏览器",
    "Customizations": "自定义", "Projects": "项目", "Conversations": "对话",
    "New Conversation": "新建对话", "Create New Project": "创建新项目", "No conversations yet": "暂无对话",
    "Search Conversations": "搜索对话", "Display Options": "显示选项", "Project options": "项目选项",
    "Automations": "自动化", "Scheduled Tasks": "计划任务", "Provide Feedback": "提供反馈",
    "Welcome back,": "欢迎回来，", "Where should we pick up?": "我们要从哪里继续？", "Hey": "嗨",
    "Open Settings": "打开设置", "Close": "关闭", "Save": "保存", "Cancel": "取消",
    "Apply": "应用", "Reset": "重置", "Advanced": "高级", "Language": "语言",
    "Theme": "主题", "System": "系统", "Light": "浅色", "Dark": "深色",
    "Font": "字体", "Font Size": "字体大小", "Volume": "音量", "Microphone": "麦克风",
    "Interface Layout": "界面布局", "Knowledge Work": "知识工作", "Software Engineering": "软件开发",
    "Permissions": "权限", "Execution": "执行", "Voice mode": "语音模式", "Remote Control": "远程控制",
    "This Computer": "此电脑", "Remote": "远程", "Default": "默认", "Turbo": "高速",
    "Local permissions": "本地权限", "Request Review": "请求审阅",
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
    return f"""
/* {MARKER} */
(function () {{
  const DICT = {dictionary};
  const SKIP = new Set(['INPUT','TEXTAREA','PRE','CODE','SCRIPT','STYLE']);
  const translate = (text) => {{
    if (!text || !text.trim()) return text;
    let value = text;
    Object.keys(DICT).sort((a,b) => b.length - a.length).forEach((key) => {{
      value = value.split(key).join(DICT[key]);
    }});
    return value;
  }};
  const visit = (node) => {{
    if (!node || (node.nodeType === 1 && SKIP.has(node.tagName))) return;
    if (node.nodeType === 3) {{
      const raw = node.nodeValue || '';
      const next = raw.trim() === 'Local' ? raw.replace('Local', '本地') : translate(raw);
      if (next !== node.nodeValue) node.nodeValue = next;
      return;
    }}
    if (node.nodeType !== 1) return;
    if ((node.closest && node.closest('a[href*="/c/"]')) ||
        (node.tagName === 'A' && /\/c\//.test(node.getAttribute('href') || ''))) return;
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


def check() -> int:
    print(f"Antigravity: {APP}")
    if not APP.exists() or not ASAR.exists():
        print("结果：未找到原始 app.asar")
        return 2
    current = app_version()
    print(f"版本：{current}")
    print(f"架构：{os.uname().machine}")
    print(f"app.asar SHA-256：{sha256(ASAR)}")
    paths = set(list_paths(read_asar_tree(ASAR)))
    candidates = sorted(path for path in paths if path.endswith("preload.js") or path.endswith("menu.js"))
    print("候选入口：")
    for path in candidates[:20]:
        print(f"  - {path}")
    required = {"dist/preload.js", "dist/menu.js"}
    supported = version_tuple(current) >= MIN_SUPPORTED and required.issubset(paths)
    print("结果：结构可识别，可以进入副本试运行" if supported else "结果：暂不支持自动安装")
    print("注意：这还不是安装；不会改动应用。")
    return 0 if supported else 1


def install(force: bool) -> int:
    if check() != 0 and not force:
        print("未通过检查，未执行安装。需要明确使用 --force 才会继续。")
        return 1
    if not ASAR.exists():
        print("找不到 app.asar")
        return 2
    if UNPACKED.exists() or DISABLED_ASAR.exists():
        print("检测到已有汉化/解包状态，先使用 restore。")
        return 1
    reuse_backup = False
    if BACKUP.exists():
        if ASAR.exists() and sha256(BACKUP) == sha256(ASAR):
            reuse_backup = True
            print(f"复用未改变的原始备份：{BACKUP}")
        else:
            print(f"备份已存在且与当前 app.asar 不一致：{BACKUP}")
            return 1
    if subprocess.run(["pgrep", "-f", "/Applications/Antigravity.app"], stdout=subprocess.DEVNULL).returncode == 0:
        print("请先完全退出 Antigravity，再运行 install。")
        return 1
    with tempfile.TemporaryDirectory(prefix="antigravity-zh-") as temp:
        staging = Path(temp) / "app"
        extract_asar(ASAR, staging)
        preload = staging / "dist" / "preload.js"
        if not preload.exists():
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
    print("安装完成。请启动 Antigravity 检查界面；还原命令：restore")
    return 0


def restore() -> int:
    if not BACKUP.exists():
        print("没有找到汇芯备份，未执行还原。")
        return 1
    if subprocess.run(["pgrep", "-f", "/Applications/Antigravity.app"], stdout=subprocess.DEVNULL).returncode == 0:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="汇芯 Antigravity 中文界面安全切换器")
    parser.add_argument("command", choices=["check", "install", "restore"])
    parser.add_argument("--force", action="store_true", help="跳过版本检查；仅在确认兼容时使用")
    args = parser.parse_args()
    if args.command == "check":
        return check()
    if args.command == "install":
        return install(args.force)
    return restore()


if __name__ == "__main__":
    raise SystemExit(main())
