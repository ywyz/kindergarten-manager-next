# 当前任务

## 2026-11-22 教师反馈与 Dependabot #21

开发基线为 `dev/0.1` 的 `e0bc2b4`。本轮在 `fix/desktop-feedback-20261122` 修复，Codex 独立验收后普通提交、推送，并整合到开发分支。用户另行授权将 #21 单项依赖补丁同步到 `main`、开发及本轮修复分支。交付范围为源码，打包暂缓。

- 从工作台进入日计划先显示月历，点选日期后打开该日完整的一日活动计划。常用操作依次为「拆分教案并修改」「修改指定内容」「保存」「导出 Word」。
- 各记录编辑页提供一个「任务」入口，可查看该记录的 AI 任务和版本历史。倾听和课程审议从本轮起每次保存完整版本，支持打开查看。工作台、模块列表、各编辑页、设置和管理页均按实际用途精简重复操作。
- 工作台主页提供「在线反馈」，教师已连接或未连接在线协作时都可直接打开反馈表单。
- 更新下载使用 `https://github.ywyz.tech/` 加原始 GitHub 文件地址。使用教师提供的 WebDAV 地址 `https://data.cstcloud.cn/dav/` 核实证书验证故障。
- OpenCode 使用 GLM-5.3，Command Code 使用 GLM-5.3 Flash。各会话维护互斥文件，Codex 用合成数据验证修复、将失败项退回原会话，并维护规格和验收记录。

本轮源码已通过 Codex 独立验收，日计划按最后确认的月历入口交付。修复内容、实测结果及环境限制见[11 月 22 日验收记录](../bootstrap/desktop-preview-feedback-20261122-review.md)。

## 此前交付

- [11 月 19–20 日修复、WebDAV 及在线反馈验收](../bootstrap/desktop-preview-feedback-20261119-review.md)
- [11 月 18 日体验修复、MySQL 联调及签名预览](../bootstrap/desktop-preview-feedback-20261118-review.md)
- [11 月 17 日体验修复](../bootstrap/desktop-preview-feedback-20261117-review.md)
- [在线更新修复及 20261117 预览](../bootstrap/desktop-update-fix-20261117-review.md)
