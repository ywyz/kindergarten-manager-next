# 外置浏览器代理修复（2026-10-05）

状态：外置 Edge 已恢复新建远程页面、DOM 读取、实际登录、点击系统设置与读取持久化配置。本记录不表示 AI C1–C7 全部通过。用户在验收过程中明确要求按以前修复记录检查代理并修复连接。

初始外置 Edge 两次创建失败，错误为 `Unable to load browser request-header policy. Retry the browser command.`；清单同时报告 `Timed out waiting for Statsig values.`。内置真实浏览器可访问远程站，已经执行部分设置验收，其证据与外置修复后证据分开。

旧运行时 `81ea4d5168ddd0a3` 路径已经不存在。实际运行 Node 和启动器位于 `C:\Users\yw980\AppData\Local\OpenAI\Codex\runtimes\cua_node\45309f9050f7314b\bin`。当前启动器原 SHA-256 为 `3E52A41F4DA41D35BE8CC3723FE97251711087A998C1ED7F2CFDF7E20B50FC2B`，与此前未补丁原件相同，且没有代理注入。应用更换运行时后原补丁不再存在是现场事实；不声称已经追踪具体更新过程。

`127.0.0.1:7890` 由既有 FlClashCore 监听。curl 经该代理访问 example.com 返回 200。先备份当前 launch.js，再在其原子进程 env 合并点恢复与 [10 月 2 日记录](browser-repair-and-i5-capabilities-2026-10-02.md)相同的最小代理字段：NODE_USE_ENV_PROXY=1，HTTP/HTTPS 大小写变量指向该回环代理，NO_PROXY 保留原条目并合并 localhost、127.0.0.1、::1。

没有替换整份其他版本文件；反向移除补丁逐字等于原件。新文件 SHA-256 为 `481DEDE49A4D70F714E4BF5EED4140B0891EA52FFA3B03FE4C6283A8A2396511`，与历史补丁结果相同。该运行时 Node `--check` 通过，启用环境代理的 Node fetch example.com 返回 200。备份在 launch.js 同目录，以 `launch.js.bak-proxy-20261005-` 开头。

本次 `cua_repl.js_reset` 后，provider 3／type=extension 的 Edge 实际创建远程验收页成功，显示登录表单；使用交接测试账号真实登录并点击系统设置，重读配置 version=4、has_secret=false，与修复前已清除状态一致。本次没有完全重启 Codex；不沿用历史“仅重置不足”的结果来替代当前实测。截图留私密交接目录 logs/screenshots/edge-repaired-settings.png。

官方 [扩展排障说明](https://learn.chatgpt.com/docs/chrome-extension)已现场阅读；代理注入仍为历史社区绕行方法，不声称官方修复。未安装依赖／Skill／MCP，未改系统代理、扩展权限、业务代码、远程部署或主密钥，未 commit/push。用户其他浏览器标签未关闭。后续应用更新可能再次覆盖此运行时补丁。

2026-10-07 用户另行授权将本修复记录与桌面验收报告提交并推送，供 WSL 环境审阅；上述“未 commit/push”描述修复执行阶段。运行时文件及私密证据不进入仓库。
