# 文档与报告索引

更新：2026-10-07。当前待办以 [实施准备清单](architecture-v1-readiness.md) 和 [AGENTS.md](../../AGENTS.md) 为准。架构、ADR、模块 Contract 与 Feature 规格分别存放，不以历史操作提示词替代有效规格。

## 当前工作：AI 1C 剩余验收夹具

- [夹具方案](ai-slice1c-fixture-plan-2026-10-07.md)：真实契约演进及缺／错主密钥的隔离范围与资源门槛。
- [最新真库复审](ai-slice1c-fixture-mysql-review-2026-10-07.md)：本片 37 项（含 14 项真库）全部通过、零 skip；38 项离线单元及清理入口临时探针通过；两项测试加固由 OpenCode 写入。
- [远程准备实际结果](ai-slice1c-fixture-remote-preparation-result-2026-10-07.md)：用户授权后独立实例、正常 v1 与 B_contract 实际恢复已完成；[Windows 交接](ai-slice1c-fixture-windows-handoff-2026-10-07.md)已形成，契约发布／密钥故障及桌面补验待阶段授权。
- [远程准备执行清单](ai-slice1c-fixture-remote-preparation-plan-2026-10-07.md)：本轮已执行范围，实际身份以结果报告为准。
- [本机资源清单](ai-slice1c-fixture-mysql-plan-2026-10-07.md)已授权并完成，专用容器已停止，volume／私密配置保留；[OpenCode 交接](ai-slice1c-fixture-mysql-opencode-prompt-2026-10-07.md)与[第三轮复审](ai-slice1c-fixture-repair3-review-2026-10-07.md)保留过程身份。
- [Windows 验收与补验报告](ai-slice1c-desktop-validation-2026-10-05.md)、[桌面补验提示词](ai-slice1abc-desktop-codex-prompt-2026-10-05.md)：方案 A 已确认，剩余受阻子例不能宣布通过。

隔离真库验证已通过，远程准备已完成、真实补验尚待执行；整组提示词、交付与审阅文档暂时保留，收口后再合并。本文不放行真库资源、远程准备、部署或其他切片。

## 已收口报告与部署身份

| 事项 | 最终审阅／验收记录 | 配套规格／来源 |
| --- | --- | --- |
| I1 账号 | [MySQL 验证](i1-mysql-validation.md) | [账号规格](../specs/identity-registration-and-access.md) |
| I2 班级、学期、日历 | [实施与验证](i2-implementation-status.md) | [班级与日历规格](../specs/class-assignment-and-calendar.md) |
| I3 日计划 | 证据在规格中保留 | [日计划规格与验证](../specs/manual-daily-plan-save.md) |
| I4 周计划与确认 | 证据在规格中保留 | [I4 规格](../specs/manual-weekly-plan-confirmation.md) |
| I5 已实现 Word 链路 | [正式收口](i5-final-closeout-2026-10-03.md) | [导出规格](../specs/word-export-implementation.md)、[验收环境](../specs/i5-validation-environment.md) |
| AI 1A 数据、迁移与服务 | [阶段收口](ai-slice1a-closeout-review-2026-10-04.md) | [详细工程清单](ai-slice1a-implementation-checklist-2026-10-03.md) |
| AI 1B API 与权限 | [阶段收口](ai-slice1b-closeout-review-2026-10-04.md) | [API 规格](../specs/ai-settings-api-1b.md) |
| AI 1C 设置前端 | [实现阶段收口](ai-slice1c-closeout-review-2026-10-05.md) | [UI 规格](../specs/ai-settings-ui-1c.md)、上方 Windows 报告 |
| 1ABC 当前部署 | [实际部署结果](ai-slice1abc-deployment-result-2026-10-05.md) | [部署源 JSON](ai-slice1abc-deployment-source-2026-10-05.json)、[当时部署方案](ai-slice1abc-deployment-plan-2026-10-05.md) |
| 浏览器工具 | [最新代理修复](browser-proxy-repair-2026-10-05.md) | [浏览器与 Word 能力实证](browser-repair-and-i5-capabilities-2026-10-02.md) |

I5 的 D／F／G／H 报告覆盖不同案例、版本或证据窗口，在最终收口中逐一引用；不是同一事项的重复版本，继续保留。对应 JSON、下载文件、截图、完整性记录及历史部署源也保留，避免丢失验收依据。早期自动检查及权限报告仅证明各自执行范围，不代表新的全量验收。

## 后续规格与交接

[协同规格索引](../specs/ai-capabilities-implementation.md)关联 AI Service、提示词、持久任务与材料；P1–P4 已确认。1A／1B／1C 已实现，其他切片尚未实施。

[后续切片 OpenCode 模板](ai-capabilities-opencode-prompt-2026-10-03.md)只供用户具体授权后的未实现切片使用，不重做 1A／1B／1C。材料参考见 [提取记录](i5-material-reference-extraction-2026-10-03.md)及配套 JSON。

## 文档保留规则

已完成事项的旧编码／补修提示词及中间重复审阅报告已清除，改为引用上述最终记录；历史版本可从 Git 查询。最终记录保留执行者、测试范围、未独立复跑事项和产品验收限制，不把历史失败改写成通过。进行中的交接依赖待收口后清理，独立部署身份、原始证据及产品决定持续保留。
