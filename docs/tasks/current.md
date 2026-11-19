# 当前任务

## 2026-11-19 预览反馈修复及内部测试功能

教师确认在线更新成功。以签名预览对应修复线 `fix/preview-feedback-20261117` 的 `fdda56f` 继续，实际已发布程序源码为 `4657454`。稳定线本轮无合并安排。

先在修复分支交付在线协作管理新增园所、班级和教师名称录入／显示，提示词编辑下拉使用实际任务和字段标签。统一桌面各模块“返回工作台”的显著入口；观察与审议栏目放在左侧；倾听默认整册预览，使用“AI 生成全部”和“定向修改”。显式调用时，以当前表单及其中所选内容为输入，含尚未保存的可编辑草稿。候选经教师审核后采用，提交之后的手工编辑需要保护。倾听图片先识别老师笔迹，确无文字时由 AI 根据画面拟写待审核文字。

原生实现会话文件责任互斥。A OpenCode Go 负责在线管理及提示词，B Command Code GOAT 负责共用入口、观察与审议布局，C OpenCode Go 负责倾听、图像候选和定向接口，D OpenCode Go 负责日／周计划当前表单 AI 输入及采用。缺陷退回原会话。Codex 记录规格、执行独立审核与隔离编译运行测试，核对通过后提交修复分支并合入 `dev/0.1`。OpenCode Go 可用 GLM-5.3／DeepSeek V4.1 Flash，Command Code GOAT 可用 GLM-5.3 Flash／DeepSeek V4.1 Flash。推理强度 max。

修复合入后在开发分支启动两项新功能。WebDAV 在线备份及跨机恢复沿用一致性快照，面向个人数据和应用配置。应用内在线反馈集中到管理站处理。两项按[开发范围](../specs/desktop-webdav-and-online-feedback.md)各自经 Codex 审核、退回修订和隔离源码验收，再普通提交推送。

验证使用隔离源码、档案、凭据、导出目录和在线测试服务。可显式发真实 AI。教师原件可只读复制后拆分测试，OneDrive 原件不得修改。隔离协作测试使用合成园所、班级和两个教师。线上只读检查与隔离业务验证分别记录。用户追加授权将通过审核和隔离测试的在线服务部署到 manager-next.ywyz.tech。使用既有 SSH 主机 `ecs-user@aliyun.ywyz.tech`、现有服务单元及回源，记录候选身份、备份与回滚路径、数据库迁移和公网复验。桌面构建按源码验证交付。

在线管理提交 `278a961` 已部署，修复候选已通过独立编译、运行和专项验收。[本轮修复审核与复验](../bootstrap/desktop-preview-feedback-20261119-review.md)


## dev/0.1 新功能实现阶段

修复提交 `54c5887d64587f22a0af033a8fbd027f4b023903` 已快进至 `dev/0.1` 并推送。在线管理已部署。两个新功能按[开发范围](../specs/desktop-webdav-and-online-feedback.md)并行开工，下一次提交前由 Codex 独立审核和复验。

- W OpenCode Go 独占备份恢复宿主、WebDAV 传输与存储、备份面板、首次设置恢复入口及对应测试。
- F Command Code GOAT 独占协作网站与本地反馈接口、设置页反馈入口、增量 0007 迁移和对应测试。生产部署由 Codex 负责。
- 两个会话均按 max 推理，分别在白名单内写入。源码测试用隔离档案、WebDAV 服务、合成反馈和独立 MySQL，教师原件留在原位。

在线反馈提交 `b8db80b` 已独立验收、推送并上线。管理页可查看并处理反馈，生产数据库增量 0007 已验。WebDAV 已通过 Codex 回修审核、隔离源码编译、跨档案恢复、Edge 工作流及 Windows 原生入口检查。本轮桌面验证使用隔离资料，AI 流程采用合成响应。[审核、测试与上线记录](../bootstrap/desktop-preview-feedback-20261119-review.md)

## 前序证据

- [11 月 18 日体验修复、MySQL 联调及 20261119 预览](../bootstrap/desktop-preview-feedback-20261118-review.md)
- [11 月 17 日体验修复](../bootstrap/desktop-preview-feedback-20261117-review.md)
- [在线更新修复及 20261117 预览](../bootstrap/desktop-update-fix-20261117-review.md)
