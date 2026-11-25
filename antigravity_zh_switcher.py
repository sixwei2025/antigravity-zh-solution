#!/usr/bin/env python3
"""汇芯 Antigravity 中文界面安全切换器。

默认只检查，不修改应用。安装模式会先备份 app.asar，再使用 Electron 的
app 目录加载方式注入可回滚的 DOM 翻译层。它不会读取账号、对话或网络凭据。
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path


APP = Path("/Applications/Antigravity.app")
RESOURCES = APP / "Contents" / "Resources"
ASAR = RESOURCES / "app.asar"
DISABLED_ASAR = RESOURCES / "app.asar.disabled"
BACKUP = Path.home() / "Library" / "Application Support" / "huixin-antigravity-zh" / "app.asar.huixin-backup"
UNPACKED = RESOURCES / "app"
MARKER = "Huixin Antigravity Chinese Localization"
END_MARKER = f"{MARKER} END"
MENU_MARKER = f"{MARKER} Native Menu"
TRAY_MARKER = f"{MARKER} Native Tray"
SIDECAR_MARKER = f"{MARKER} Sidecar"
MIN_SUPPORTED = (2, 21, 1)

SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "huixin-antigravity-zh"
GUARD_SCRIPT = SUPPORT_DIR / "antigravity_zh_switcher.py"
GUARD_APP = SUPPORT_DIR / "HuixinZhGuard.app"
GUARD_BIN = GUARD_APP / "Contents" / "MacOS" / "HuixinZhGuard"
GUARD_STATE = SUPPORT_DIR / "guard_state.json"
GUARD_LOG = SUPPORT_DIR / "guard.log"
GUARD_LOCK = SUPPORT_DIR / "guard.lock"
LAUNCH_AGENT_LABEL = "com.huixin.antigravity-zh-guard"
LAUNCH_AGENT_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"

DICT_LOAD_ORDER = [
    "common.json",
    "menu_nav.json",
    "page_agents.json",
    "page_main.json",
    "page_mcp_knowledge.json",
    "page_settings.json",
    "huixin_polish.json",
]

NATIVE_MENU_TRANSLATIONS = {
    "File": "文件",
    "Edit": "编辑",
    "View": "视图",
    "Window": "窗口",
    "Help": "帮助",
    "New Window": "新建窗口",
    "Create Project": "创建项目",
    "Command Palette": "命令面板",
    "Docs": "文档",
    "Check for Updates": "检查更新",
    "Checking for Updates...": "正在检查更新...",
    "Downloading Update...": "正在下载更新...",
    "Restart to Update": "重启以更新",
    "Toggle Developer Tools": "切换开发者工具",
    "Undo": "撤销",
    "Redo": "重做",
    "Cut": "剪切",
    "Copy": "复制",
    "Paste": "粘贴",
    "Paste and Match Style": "粘贴并匹配样式",
    "Delete": "删除",
    "Select All": "全选",
    "Minimize": "最小化",
    "Maximize": "最大化",
    "Close": "关闭",
    "Close Window": "关闭窗口",
    "Zoom": "缩放",
    "Reset Zoom": "重置缩放",
    "Actual Size": "实际大小",
    "Zoom In": "放大",
    "Zoom Out": "缩小",
    "Toggle Full Screen": "切换全屏",
    "Bring All to Front": "前置全部窗口",
    "Toggle Between Light/Dark Themes": "切换浅色/深色主题",
    "Split Terminal": "拆分终端",
    "Split Conversation Horizontally": "水平拆分对话",
    "Split Conversation Vertically": "垂直拆分对话",
    "Split": "拆分",
    "Split Right": "向右拆分",
    "Split Down": "向下拆分",
    "Replace With New": "替换为新对话",
    "Show in File Explorer": "在文件管理器中显示",
    "Reveal in Finder": "在访达中显示",
    "Find in conversation": "在对话中查找",
    "Connect to WSL": "连接到 WSL",
    "Reopen Locally": "在本地重新打开",
    "About Antigravity": "关于 Antigravity",
    "Settings...": "设置...",
    "Preferences...": "偏好设置...",
    "Services": "服务",
    "Hide Antigravity": "隐藏 Antigravity",
    "Hide Others": "隐藏其他",
    "Show All": "全部显示",
    "Quit Antigravity": "退出 Antigravity",
    "Quit": "退出",
    "Open Antigravity": "打开 Antigravity",
    "Version": "版本",
}


def resolve_asset_dir(name: str) -> Path:
    local_dir = Path(__file__).resolve().parent / name
    if local_dir.is_dir():
        return local_dir
    support_dir = SUPPORT_DIR / name
    if support_dir.is_dir():
        return support_dir
    raise RuntimeError(f"找不到资源目录：{name}（已检查 {local_dir} 与 {support_dir}）")


def load_dictionary() -> dict[str, str]:
    dicts_dir = resolve_asset_dir("dicts")
    merged: dict[str, str] = {}
    for filename in DICT_LOAD_ORDER:
        file_path = dicts_dir / filename
        if not file_path.exists():
            continue
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, str):
                    merged[k] = v
    return merged


def version_tuple(value: str) -> tuple[int, int, int]:
    parts = (value.split(".") + ["0", "0", "0"])[:3]
    out = []
    for part in parts:
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out)  # type: ignore[return-value]


def app_version() -> str:
    plist_path = APP / "Contents" / "Info.plist"
    if not plist_path.exists():
        return "unknown"
    try:
        with plist_path.open("rb") as handle:
            info = plistlib.load(handle)
        return str(info.get("CFBundleShortVersionString", "unknown"))
    except Exception:
        return "unknown"


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
    runtime_path = resolve_asset_dir("runtime") / "preload_runtime.js"
    if not runtime_path.exists():
        raise RuntimeError(f"找不到运行时文件：{runtime_path}")
    dictionary = json.dumps(load_dictionary(), ensure_ascii=False, separators=(",", ":"))
    runtime_js = runtime_path.read_text(encoding="utf-8")
    runtime_js = runtime_js.replace("__USE_TW_PLACEHOLDER__", "false").replace("DICT_PLACEHOLDER", dictionary)
    return f"\n/* {MARKER} */\n{runtime_js}\n/* {END_MARKER} */\n"


def inject(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if MARKER in text:
        return True
    path.write_text(text.rstrip() + "\n" + make_injection(), encoding="utf-8")
    return True


def inject_native_menu(path: Path) -> bool:
    """Wrap Electron's application menu setter with exact-match Chinese labels."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if MENU_MARKER in text:
        return True
    dictionary = json.dumps(NATIVE_MENU_TRANSLATIONS, ensure_ascii=False, separators=(",", ":"))
    wrapper = f"""
/* {MENU_MARKER} */
(function () {{
  const DICT = {dictionary};
  const LOWER_DICT = Object.fromEntries(Object.entries(DICT).map(([k, v]) => [k.toLowerCase(), v]));
  const translateLabel = (value) => {{
    if (!value || typeof value !== 'string') return value;
    const trimmed = value.replace(/&([a-zA-Z])/g, '$1').trim();
    if (!trimmed) return value;
    if (Object.prototype.hasOwnProperty.call(DICT, trimmed)) return DICT[trimmed];
    const lower = trimmed.toLowerCase();
    if (Object.prototype.hasOwnProperty.call(LOWER_DICT, lower)) return LOWER_DICT[lower];
    return value;
  }};
  const walk = (menu) => {{
    if (!menu || !menu.items) return;
    menu.items.forEach((item) => {{
      if (item.label) item.label = translateLabel(item.label);
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


def inject_tray(path: Path) -> bool:
    """Localize macOS menu bar tray items and active agent count."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if TRAY_MARKER in text:
        return True
    dictionary = json.dumps(NATIVE_MENU_TRANSLATIONS, ensure_ascii=False, separators=(",", ":"))
    tray_js = f"""
/* {TRAY_MARKER} */
(function () {{
  const DICT = {dictionary};
  const LOWER_DICT = Object.fromEntries(Object.entries(DICT).map(([k, v]) => [k.toLowerCase(), v]));
  const translateLabel = (value) => {{
    if (!value || typeof value !== 'string') return value;
    const trimmed = value.trim();
    if (!trimmed) return value;
    if (Object.prototype.hasOwnProperty.call(DICT, trimmed)) return DICT[trimmed];
    const lower = trimmed.toLowerCase();
    if (Object.prototype.hasOwnProperty.call(LOWER_DICT, lower)) return LOWER_DICT[lower];
    const m = trimmed.match(/^(\\d+|No)\\s+agents?\\s+running$/i);
    if (m) {{
      return m[1].toLowerCase() === 'no' ? '暂无运行中的智能体' : m[1] + ' 个智能体运行中';
    }}
    return value;
  }};
  try {{
    const electron = require('electron');
    const origBuild = electron.Menu.buildFromTemplate;
    electron.Menu.buildFromTemplate = function (template) {{
      if (Array.isArray(template)) {{
        template = template.map((item) => item && item.label ? Object.assign({{}}, item, {{ label: translateLabel(item.label) }}) : item);
      }}
      return origBuild.call(this, template);
    }};
    const origMenuItem = electron.MenuItem;
    electron.MenuItem = function (options) {{
      if (options && options.label) {{
        options = Object.assign({{}}, options, {{ label: translateLabel(options.label) }});
      }}
      return new origMenuItem(options);
    }};
    electron.MenuItem.prototype = origMenuItem.prototype;
  }} catch (_) {{}}
}})();
"""
    # Also localize updateTrayAgentCount inline if present
    text = text.replace(
        "(count > 0 ? `${count}` : 'No') +\n                    ' agent' +\n                    (count === 1 ? '' : 's') +\n                    ' running'",
        "(count > 0 ? `${count} 个智能体运行中` : '暂无运行中的智能体')",
    )
    path.write_text(text.rstrip() + "\n" + tray_js, encoding="utf-8")
    return True


def inject_sidecar(path: Path) -> bool:
    """Inject Sidecar iframe localization hook into dist/utils.js."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if SIDECAR_MARKER in text:
        return True
    target = "hubContents.on('will-navigate', guardExternalNavigation);"
    idx = text.find(target)
    if idx == -1:
        return False
    hook = f"""/* {SIDECAR_MARKER} */
    const getSidecarLocalizationScript = () => {{
        const preloadFile = typeof path_1 !== 'undefined' && path_1 && path_1.default
            ? path_1.default.join(__dirname, 'preload.js')
            : require('path').join(__dirname, 'preload.js');
        const cacheKey = '__huixinSidecarScript:' + preloadFile;
        if (typeof globalThis[cacheKey] === 'string') return globalThis[cacheKey];
        try {{
            const fsMod = typeof fs !== 'undefined' && fs && typeof fs.readFileSync === 'function' ? fs : require('fs');
            const src = fsMod.readFileSync(preloadFile, 'utf8');
            const sIdx = src.indexOf('/* {MARKER} */');
            const eIdx = sIdx !== -1 ? src.indexOf('/* {END_MARKER} */', sIdx) : -1;
            if (sIdx !== -1 && eIdx !== -1) {{
                const extracted = src.slice(sIdx, eIdx + '/* {END_MARKER} */'.length);
                globalThis[cacheKey] = extracted;
                return extracted;
            }}
        }} catch (_) {{}}
        return '';
    }};
    const injectSidecarSubframe = (frame) => {{
        try {{
            const winDestroyed = typeof win !== 'undefined' && win && win.isDestroyed?.();
            if (!frame || frame.isDestroyed?.() || winDestroyed || hubContents.isDestroyed?.()) return;
            const mainFrame = hubContents.mainFrame;
            if (!mainFrame || frame === mainFrame || frame.parent !== mainFrame) return;
            const frameUrl = String(frame.url || '');
            if (!/^(?:https?|plugin):\\/\\//i.test(frameUrl)) return;
            const script = getSidecarLocalizationScript();
            if (!script) return;
            frame.executeJavaScript(script).catch(() => undefined);
        }} catch (_) {{}}
    }};
    hubContents.on('did-frame-navigate', (e, _u, _c, _t, isMain, pid, rid) => {{
        if (!isMain) injectSidecarSubframe(e?.frame || electron_1.webFrameMain?.fromId?.(pid, rid));
    }});
    hubContents.on('did-frame-finish-load', (e, isMain, pid, rid) => {{
        if (!isMain) injectSidecarSubframe(e?.frame || electron_1.webFrameMain?.fromId?.(pid, rid));
    }});
    """
    path.write_text(text[:idx] + hook + text[idx:], encoding="utf-8")
    return True


def is_app_running() -> bool:
    if (
        subprocess.run(
            ["pgrep", "-f", "/Applications/Antigravity.app/Contents/MacOS/Antigravity"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    ):
        return True
    try:
        res = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if line.strip() == "/Applications/Antigravity.app/Contents/MacOS/Antigravity":
                    return True
    except Exception:
        pass
    return False


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


def resolve_source_asar() -> Path | None:
    if ASAR.exists():
        return ASAR
    if DISABLED_ASAR.exists():
        return DISABLED_ASAR
    if BACKUP.exists():
        return BACKUP
    return None


def check(quiet: bool = False) -> int:
    if not quiet:
        print(f"Antigravity: {APP}")
    source_asar = resolve_source_asar()
    if not APP.exists() or source_asar is None:
        if not quiet:
            print("结果：未找到原始 app.asar")
        return 2
    current = app_version()
    paths = set(list_paths(read_asar_tree(source_asar)))
    candidates = sorted(
        path for path in paths
        if path.endswith("preload.js") or path.endswith("menu.js") or path.endswith("tray.js") or path.endswith("utils.js")
    )
    required = {"dist/preload.js", "dist/menu.js"}
    supported = version_tuple(current) >= MIN_SUPPORTED and required.issubset(paths)
    if not quiet:
        print(f"版本：{current}")
        print(f"架构：{os.uname().machine}")
        print(f"来源：{source_asar.name}（SHA-256：{sha256(source_asar)}）")
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
    source_asar = resolve_source_asar()
    if source_asar is None:
        if not quiet:
            print("找不到 app.asar")
        return 2
    if is_app_running():
        if not quiet:
            print("请先完全退出 Antigravity，再运行 install。")
        return 1
    # 官方升级可能会覆盖出新的 app.asar，同时残留旧的 app/ 或 app.asar.disabled；安全清理后再重装
    if source_asar == DISABLED_ASAR and not ASAR.exists():
        DISABLED_ASAR.rename(ASAR)
        source_asar = ASAR
    elif source_asar == BACKUP and not ASAR.exists():
        shutil.copy2(BACKUP, ASAR)
        source_asar = ASAR
    if UNPACKED.exists():
        shutil.rmtree(UNPACKED)
    if DISABLED_ASAR.exists():
        DISABLED_ASAR.unlink()
    reuse_backup = False
    if BACKUP.exists():
        if sha256(BACKUP) == sha256(source_asar):
            reuse_backup = True
            if not quiet:
                print(f"复用未改变的原始备份：{BACKUP}")
        else:
            if not quiet:
                print(f"检测到官方版本已更新，刷新原始备份：{BACKUP}")
    with tempfile.TemporaryDirectory(prefix="antigravity-zh-") as temp:
        staging = Path(temp) / "app"
        extract_asar(source_asar, staging)
        preload = staging / "dist" / "preload.js"
        if not preload.exists():
            if not quiet:
                print("当前版本没有找到 dist/preload.js，已停止，未改动应用。")
            return 1
        inject(preload)
        inject_native_menu(staging / "dist" / "menu.js")
        inject_tray(staging / "dist" / "tray.js")
        inject_sidecar(staging / "dist" / "utils.js")
        # 保留解包目录，Electron 会在 app.asar.disabled 时加载它。
        if not reuse_backup:
            SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_asar, BACKUP)
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
    if not (UNPACKED.exists() and DISABLED_ASAR.exists() and not ASAR.exists() and preload.exists()):
        return False
    try:
        return MARKER in preload.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False


def prompt_restart_for_localization(version: str) -> bool:
    """弹窗询问用户是否立即重启 Antigravity 以恢复中文界面。"""
    try:
        msg = f"检测到 Antigravity 已更新到 {version}，官方更新覆盖了中文界面。是否立即重启以自动恢复中文？"
        script = (
            f'display dialog {json.dumps(msg)} '
            'with title "汇芯 Antigravity 汉化守护" '
            'buttons {"稍后（退出时自动恢复）", "立即重启恢复中文"} '
            'default button "立即重启恢复中文" '
            'giving up after 60'
        )
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=65)
        return res.returncode == 0 and "立即重启恢复中文" in (res.stdout or "")
    except Exception:
        return False


def quit_app_and_wait(timeout_sec: float = 8.0) -> bool:
    """温和退出 Antigravity 并等待进程结束。"""
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Antigravity" to quit'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        pass
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not is_app_running():
            return True
        time.sleep(0.4)
    return not is_app_running()


def _auto_sync_locked() -> int:
    if not APP.exists() or not (APP / "Contents" / "Info.plist").exists():
        return 0
    if is_localized():
        return 0
    if not ASAR.exists():
        return 0

    current = app_version()
    if current == "unknown":
        return 0
    try:
        supported = check(quiet=True) == 0
    except Exception:
        # 升级替换瞬间文件可能尚未就绪，留待下一次轮询处理
        return 0
    if not supported:
        state = load_guard_state()
        if state.get("incompatible_notified") != current:
            log_guard(f"检测到 Antigravity {current} 结构不兼容，已跳过自动汉化")
            notify("汇芯 Antigravity 汉化守护", f"检测到新版本 {current} 结构有变化，暂未自动汉化，请检查工具更新。")
            state["incompatible_notified"] = current
            save_guard_state(state)
        return 1

    restarted_by_guard = False
    if is_app_running():
        state = load_guard_state()
        if state.get("prompted_version") != current:
            log_guard(f"检测到 Antigravity {current} 汉化已失效（升级覆盖），弹窗询问是否立即重启恢复")
            state["prompted_version"] = current
            state["pending_notified"] = current
            save_guard_state(state)
            if prompt_restart_for_localization(current):
                if quit_app_and_wait(timeout_sec=8.0):
                    restarted_by_guard = True
                else:
                    log_guard(f"Antigravity {current} 未在 8 秒内退出，等待用户手动退出后自动恢复")
                    notify("汇芯 Antigravity 汉化守护", "请先手动完全退出 Antigravity，退出后 5 秒内将自动恢复中文界面。")
                    return 0
            else:
                return 0
        else:
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
        log_guard(f"已自动为 Antigravity {current} 重新注入中文界面" + ("并重启" if restarted_by_guard else ""))
        state = load_guard_state()
        state["last_synced_version"] = current
        state.pop("pending_notified", None)
        state.pop("permission_notified", None)
        state.pop("prompted_version", None)
        save_guard_state(state)
        if restarted_by_guard:
            subprocess.Popen(["open", "-a", str(APP)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            notify("汇芯 Antigravity 汉化守护", f"Antigravity {current} 中文界面已自动同步完成。")
    else:
        log_guard(f"Antigravity {current} 自动汉化失败，退出码：{code}")
    return code


def auto_sync() -> int:
    """供 LaunchAgent 调用：检测到官方升级导致汉化丢失时自动重新注入。"""
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    with GUARD_LOCK.open("w", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0
        try:
            return _auto_sync_locked()
        finally:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


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


def sync_support_assets() -> None:
    """将 dicts/ 与 runtime/ 同步到 SUPPORT_DIR，供后台守护进程独立使用。"""
    source_root = Path(__file__).resolve().parent
    for folder in ("dicts", "runtime"):
        src = source_root / folder
        dst = SUPPORT_DIR / folder
        if src.is_dir() and src.resolve() != dst.resolve():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)


def guard_enable() -> int:
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).resolve(), GUARD_SCRIPT)
    GUARD_SCRIPT.chmod(0o755)
    sync_support_assets()
    has_guard_app = ensure_guard_app()
    LAUNCH_AGENT_PLIST.parent.mkdir(parents=True, exist_ok=True)
    program_args = [str(GUARD_BIN)] if has_guard_app and GUARD_BIN.exists() else [sys.executable, str(GUARD_SCRIPT), "auto-sync"]
    plist_data = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": program_args,
        "WatchPaths": [str(APP), str(RESOURCES), str(APP / "Contents" / "Info.plist")],
        "StartInterval": 5,
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
    print("以后每次 Antigravity 升级，只要退出应用，5 秒内会自动同步中文界面（若升级后自动重启为英文，会弹窗一键重启恢复）。")
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
