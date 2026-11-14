# 当前任务

## 2026-11-14 教师反馈修复

逐项变更、源码核验、暂缺证据与产品待决事项见[教师测试反馈修复报告](../bootstrap/desktop-teacher-feedback-20261114-review.md)。集成分支为 `dev/0.1`，更新修复分支为 `fix/preview-update`。请先审阅本轮修复。打包、签名及 GitHub Release 上传等待用户同意。

## 当前入口

2026-11-12 的历史合并提交为 `d1a4261`，父提交依次为签名预览源码 `54bce96` 与远端 `main` 的 `209fee5`。历史 `codex/*` 分支、旧包和原证据按对应核查记录保留。

公开 Windows 签名预览为 `v0.1.0-listening-test.20261114`（GitHub Releases）。它是在 `20261112` 签名预览基础上的修复版，不是稳定正式发行。`20261113` 是更新测试基线；公开 GitHub 下载与验签已达到 `ready` 的记录见[多设备反馈与签名预览验收](../bootstrap/desktop-multi-device-preview-review.md)。

## 仍有待验

1. 教师在个人设备上执行 `20261113 → 20261114` 更新时报告重启后仍为旧版，手动安装成功。当前修复已过合成源码 WebView2 替换与启动检查，仍待签名候选在教师设备验证，含偶发 IDM 窗口。
2. 在线协作测试部署：真实 HTTPS 管理端、学期更名、发码、选班、升班、共享周保存/确认和本地 Word 已按合成数据联调。教师正常路径复测、安装包跨设备和第二台物理设备仍待验。当前管理端可读取/更新学期名称；陈旧基准 409，写操作要求 CSRF。
3. 提示词发布：本次待发草稿覆盖 7 项任务、19 个字段，已通过线上允许列表校验；模块目录不止该草稿，测试渠道现存预览 v9、正式 v11，草稿尚未发布。普通签名 `20261114` 尚未嵌入提示词包来源及验签公钥；后续自动接收前须配置发行信任。

## 证据与接续

- 本轮合并、签名、长文本与更新结果：[多设备反馈与签名预览验收](../bootstrap/desktop-multi-device-preview-review.md)。
- 在线协作部署和管理端：[在线协作合成联调](../bootstrap/online-collaboration-integration-review.md#2026-11-12-管理端学期更名部署与联调)；模块合同见[在线协作 Contract](../modules/online-collaboration.md)。
- 备份恢复：[发布前核查](../bootstrap/desktop-backup-restore-release-review.md)。
- 一对一倾听：[L1–L4 核查](../bootstrap/desktop-one-to-one-listening-review.md)。
- 定向修改：[独立核查](../bootstrap/desktop-directional-revision-review.md)；课程审议：[源码与 Word 核查](../bootstrap/desktop-curriculum-deliberation-review.md)及[功能设计](../specs/desktop-curriculum-deliberation.md)。
- 更新规则：[应用版本更新规格](../specs/desktop-application-update.md)；提示词边界：[提示词 Contract](../modules/prompts.md)。

## 授权边界

本轮授权为反馈修复、合成验证及普通提交推送。打包、签名和上传 GitHub Release 等待用户审阅同意，真实供应商调用、生产部署和数据迁移须另行授权。
