# 汇芯·Antigravity 中文界面解决方案

当前版本：`v0.1.1`（2026-11-14）

这是一个面向 macOS Antigravity 桌面端的本地中文界面工具：把侧栏、设置页、输入提示、对话摘要、权限菜单和 macOS 应用菜单翻译成自然中文，同时保留模型名称、代码、文件内容和用户输入原样。

它默认只检查，不会自动修改应用；安装时先复制 `app.asar` 备份，再把翻译层注入副本，支持完整还原。当前已在 Antigravity `2.32.1`、Apple Silicon、含 `app.asar.unpacked` 的结构上完成验证。

## 使用

```bash
python3 antigravity_zh_switcher.py check
python3 antigravity_zh_switcher.py install
python3 antigravity_zh_switcher.py restore
```

第一次建议只运行 `check`。`install` 前需要完全退出 Antigravity；如果当前版本没有通过结构检查，工具会停止，不会修改应用。`--force` 只用于已经确认兼容的版本。

## 当前边界

它优先翻译 Antigravity 自己的网页界面、设置页、侧栏、输入框提示、对话摘要标题、权限选项和常用菜单文字；模型名称、模型生成的对话内容、代码、文件内容和用户输入不会被翻译。对话摘要标题采用安全的已知标题映射，不会把聊天正文当成界面文字翻译。官方升级后可能需要重新检查，旧版本备份不会被覆盖。正式安装前请先保存当前工作并退出应用。

不同版本的界面结构可能变化。如果升级后发现个别文字仍是英文，请先运行 `check`；不要直接覆盖备份。这个项目只提供本地界面适配，不修改模型能力、账号权限、网络设置或 Antigravity 官方服务。

## 安全说明

工具只处理本机 `/Applications/Antigravity.app` 的显示资源，不读取账号、对话、密钥或网络请求。安装会修改应用目录，因此必须保留备份；如果界面异常，退出应用后执行 `restore` 即可恢复官方英文版。

## 许可与致谢

本项目采用 MIT License。Antigravity 是其各自权利人的软件；本项目不是 Google 官方产品，也不代表 Google。感谢此前公开社区汉化项目提供的版本线索与启发，本仓库的安装器和本地适配逻辑独立维护。
