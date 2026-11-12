# 当前任务

## 当前入口

2026-11-12 的当前集成分支为 `dev/0.1`，实际合并提交 `d1a4261`，父提交依次为签名预览源码 `54bce96` 与远端 `main` 的 `209fee5`；`main` 保持现有稳定线。历史 `codex/*` 分支、旧包和原证据保留，不在本轮删除。

公开 Windows 签名预览为 `v0.1.0-listening-test.20261114`（GitHub Releases）。它是在 `20261112` 签名预览基础上的修复版，不是稳定正式发行。`20261113` 是更新测试基线；公开 GitHub 下载与验签已达到 `ready` 的记录见[多设备反馈与签名预览验收](../bootstrap/desktop-multi-device-preview-review.md)。

## 仍有待验

1. 教师在个人设备上执行 `20261113 → 20261114` 更新：检查更新、预览、下载、安装替换并重启。公开 GitHub 下载验签已完成；实际安装替换和重启尚未由用户设备确认，第二台 Windows 设备也未验。
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

本轮只按当前文档维护和已取得的合成/签名验证收口。发包、签名新版本、真实 AI、远程发布、生产数据迁移和后续平台验证均需另行明确授权；不因本页记录自动启动。
