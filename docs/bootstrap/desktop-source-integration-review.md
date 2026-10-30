# 桌面源码合入 main：独立核查

更新：2026-10-30。状态：**源码整合已独立通过，原 OpenCode 普通提交并推送，远端 main 已快进为当前桌面开发源码。** 整合提交为 `b0cc53b02c0c3f04e026ab683541a4c25c3a318a`。用户已授权接续完整本地备份／恢复；仍以源码验证为限，不发行。

## 1. 范围和基线

继续使用 `codex/desktop-v2-foundation`。公开入口文档由原 OpenCode 会话 `ses_ead8af71dffeJphI1NOWg4jZgI`、build、`opencode-go/deepseek-v4.1-flash#max` 整理，Codex 独立审核并维护本报告与任务入口。没有新实现者、会话、模型或分支。

| 执行前独立核对 | 结果 |
| --- | --- |
| 桌面 HEAD 与远端分支 | `0e45f076794e90d3522ab28164df0c5ea212e454`，fetch 后相同 |
| 远端 main | `b3c5bbf71008f34ae0da1df92f90e03994d3742f`，为桌面 HEAD 祖先；main 独有 0、桌面独有 19 |
| 工作区 | 仅 AGENTS、文档索引及 current.md 三份前轮提示词准备改动，已私下留存，保留后整合 |
| 仓库规则 | GitHub 元数据为 public、默认 main；main protected=false，分支 active rules=[]。不修改设置，不绕过规则 |
| 远端引用 | 3 个分支，dependabot 不动；无 tag，正式／其他 Release 列表共 0 |

本阶段只整理公开入口与记录；许可及业务代码使用已通过的桌面提交。默认保留原历史，允许时普通快进，不 squash／rebase／amend／强推，不自动删除桌面分支。提交和合并仅由原 OpenCode 在独立审阅通过后执行。

## 2. 独立审阅与校验

README 的 main 源码入口、维护者中英文及 Certum 链接已按待集成版本整理；合并前仍明确桌面分支为当前来源，不提前声称远端已合并。MIT／第三方入口、独立体验目录、源码禁安装更新及无稳定签名发行包的边界均保留。

Codex 独立核对全部 7 份整合文档，117 个相对文件链接有效，新增差异中的本机 Users 路径、私钥和常见供应商／GitHub token 形状无命中。`git diff --check` 退出 0；有既有 LF／CRLF 提示，不影响内容检查。补查 12 类私有代表路径均忽略、6 类公开文件不忽略。实际工作区的业务、测试、锁文件、构建脚本与资源均未变化，仍对应起始 `0e45f076…`。本次不重跑业务测试；既有源码同源证据继续按各自范围使用，不将文档整理说成新业务验收。

沿用已核查的忽略规则和当前文件隐私结果；没有新增数据库、照片、日志、密钥、备份包或模板。提交前以私有批准清单锁定路径、Git blob 和 tree，原 OpenCode 必须核对后执行，不能夹带其他改动。

历史工程证据保持各自源码身份：[AI 重试与 GitHub 更新核查 §4](desktop-retry-github-review.md#4-最终独立结论与源码交付)及[MIT 开源核查](open-source-readiness-review.md)。公开历史问题 OSS-R06 仍存在；快进不撤回旧对象，本阶段不宣称全历史安全。

## 3. Git 实际回执

原 OpenCode 的文档整理与 Git 两次 CLI 均自然 exit 0、停写；Codex 直接回读本地、远端及公开页面，结果如下：

| 核对项 | 实际结果 |
| --- | --- |
| 普通提交 | `b0cc53b02c0c3f04e026ab683541a4c25c3a318a`，唯一父提交为起始 `0e45f076794e90d3522ab28164df0c5ea212e454`，仅批准的 7 份文档 |
| 批准与实际 tree | 均为 `5ab0c581985fb9f6fe229ed10dadf7b809ca81ec`；逐文件 Git blob 一致 |
| 桌面分支 push | `0e45f076… → b0cc53b0…`，普通 push，exit 0 |
| main 快进 | `b3c5bbf7… → b0cc53b0…`，普通 `HEAD:refs/heads/main` push，exit 0；没有 merge commit、squash、rebase 或强推 |
| Codex 远端回读 | `git ls-remote` 及另行 fetch 后，两端均为完整 `b0cc53b0…`；原桌面 HEAD 和旧 main 均仍可达，桌面分支保持 |
| 公开入口 | main 的 README、LICENSE、MAINTAINERS、Certum 四页均经未认证 HTTP 读取返回 200，字节与批准提交对应 blob 一致 |
| tag／Release | 独立回读仍为 0／0；不触发应用在线升级 |
| 并行远端变化 | 合并后 fetch 发现 GitHub 新建 dependabot/pip 分支；与原 dependabot/npm 分支均未合并、删除或改写。执行前 3 个远端分支是当时快照，不宣称最后仍只有 3 个 |

随后将公开入口的待集成提示收口为实际 main 状态，并将已完成的第一段提示词归并本报告；后续文档提交不为回填自身 SHA 产生循环提交，最终身份以 Git／私有回执为准。开发继续沿用原桌面分支。

## 4. 未验与后续边界

本次不改业务实现，不制作或执行冻结包，不调用应用真实 AI，不启动 WebDAV、不改系统保护。正式签名／发行、SAC4551、最新冻结入口与安装更新、教师完整体验、MiMo、Win10／WPS／其他显示配置、原 D2／D3 未验及公开历史个人信息问题继续单列。普通 push／合并不会成为应用更新；无正式 Release 时仍为 `no_release`。

完整备份／恢复接续见[唯一当前入口](../tasks/current.md)，5 项产品决定已由用户逐项确认并归入[备份规格](../specs/desktop-backup-restore.md)，继续按片核定及实施。旧迁移数据库备份不等于全部照片及业务已备份。
