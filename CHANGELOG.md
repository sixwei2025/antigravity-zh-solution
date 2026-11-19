# 更新记录

## v0.3.1 — 2026-11-19

- 验证适配 Antigravity `2.33.0`。
- 新增 `HuixinZhGuard.app` 静默后台授权壳（`guard-enable` 时自动编译签名）：解决 macOS「App 管理」拦截后台 LaunchAgent 修改 `/Applications/Antigravity.app` 的权限问题，一次授权即可永久自动保持汉化。
- 将原始 `app.asar` 备份目录移至 `~/Library/Application Support/huixin-antigravity-zh/`，避免受应用包保护或更新清理影响。
- 优化守护响应速度（检测间隔缩短至 `15` 秒），并完善缺少权限时的桌面通知提示。

## v0.3.0 — 2026-11-18

- 适配 Antigravity `2.32.2`，补充 `No Project`、`Local Permissions`、`what should we build today?` 等界面词条。
- 新增 `guard-enable`、`guard-disable`、`guard-status`、`auto-sync` 命令：通过 macOS LaunchAgent 监听应用更新，每次 Antigravity 官方升级覆盖后，只要退出重启即可自动恢复中文界面，无需手动重新安装。
- 改进 `install` 逻辑：官方升级覆盖 `app.asar` 时自动刷新备份并清理旧版残留解包目录。

## v0.2.0 — 2026-11-14

- 按汇芯开源产品标准重构 README 首屏、安装入口、工作原理、常见问题和品牌露出。
- 增加汉化前 / 汉化后的真实横屏界面对比图。
- 增加中文适配流程架构图与开源项目矩阵。
- 明确桌面应用适配工具与 Skill 的边界，补充安全说明和诚实兼容范围。

## v0.1.1 — 2026-11-14

- 增加对话列表标题的中文摘要映射。
- 已覆盖官网改版、Gemini Hydrogen 宣传视频、本地视频宣传风格评审和语言设置位置等常见标题。
- 只处理对话列表中的已知标题，不翻译聊天正文、代码和用户输入。

## v0.1.0 — 2026-11-14

- 首次整理为可发布的 macOS Antigravity 中文界面解决方案。
- 支持 `check`、`install`、`restore` 三个命令。
- 支持 `app.asar.unpacked` 文件的安全解包与还原。
- 增加侧栏、设置、输入提示、对话摘要、权限选项和应用菜单翻译。
- 保留原始 `app.asar` 备份，避免重复安装覆盖官方文件。
- 已验证 Antigravity 2.32.1、Apple Silicon 结构。
