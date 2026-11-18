# 当前任务

## 2026-11-18 真实体验反馈修复与隔离源码验收

在 `fix/preview-feedback-20261117` 的 `bf13334` 上接续本轮教师反馈。前一轮工作台、个人待办、日计划和左栏导航列入源码回归，详见[11 月 17 日审核](../bootstrap/desktop-preview-feedback-20261117-review.md)。本轮修复 1080p 到 2K 的布局适配、周计划总览与栏目级 AI、观察和倾听编辑分栏与倾听 Word 入口、审议分栏与二次稿联动、在线园所和班级名称维护。设置按报告保留现有流程。

OpenCode Go 负责周计划与观察分栏。Command Code 负责共用布局、倾听、审议、在线名称维护和入口去重。会话保持文件责任互斥。用户追加允许 OpenCode Go 使用 GLM-5.3，Command Code 使用 GOAT 的 GLM-5.3 Flash。Codex 审核并将问题交回原会话，审核通过后执行隔离源码编译、运行及回归，核对后普通提交并推送此修复分支。

隔离环境可测试真实应用 AI、Word 副本和浏览器协作。原件仅只读复制，真实教师库和凭据不随源码或证据入仓。在线写入使用合成档案和隔离服务。本轮交付源码及审核结果，安装包和发行不在本轮范围。

本轮追加全量文档和功能入口核查。OpenCode 与 Command Code 各使用独立会话并行审阅，Codex 核对入口、合同、引用与历史证据后收口。只清理已证实重复且无独立作用的功能入口，以及已有权威去向的过时文档。

核对过程和候选证据集中在[本轮审核与验证](../bootstrap/desktop-preview-feedback-20261118-review.md)。

## 前序结果

- [在线更新修复及公开预览](../bootstrap/desktop-update-fix-20261117-review.md)保留 20261117 的构建、签名、发布和受管根更新证据。[20261116 的结果](../bootstrap/desktop-signed-test-20261116-review.md)保留第一次安装失败现场和原有渠道的发布记录。
- [11 月 17 日体验修复](../bootstrap/desktop-preview-feedback-20261117-review.md)记录本分支的工作台、待办、导航和日计划基线。
- [桌面左栏与日历回修](../bootstrap/desktop-sidebar-calendar-review.md)、[真实资料及 AI 核查](../bootstrap/desktop-real-ai-material-review.md)保留此前实现、合成数据及教师资料验证的适用范围。
