# 当前：包含周计划的 Windows 11 新候选

更新：2026-11-02。用户已授权制作包含周计划的新 Windows 11 验证包，继续调用原生 OpenCode／Command Go 的 DeepSeek V4.1 Flash max，可并行，Codex 最终审核；完成构建和静态核查后普通提交推送，并交付另一台电脑测试步骤。随后追加GitHub生成EXE供测试与更新文档，已纳入本轮。本次授权取代上一轮“本次不自动构建”的阶段限制，不扩大为真实 AI、签名或发行。分工／实际证据归[本轮核查](../bootstrap/desktop-weekly-windows11-review.md)，目标步骤见[新手册](../bootstrap/desktop-weekly-windows11-manual.md)。

## 基线与责任

继续 `codex/desktop-v2-foundation`；本轮开工 HEAD `796028b5dd90e53ce49fc9a0086bf464678789a0`，工作区干净。周计划 Q1–Q4、明暗模式及备份配套源码已收口，依据[实施核查](../bootstrap/desktop-weekly-plan-review.md)、[周产品](../specs/desktop-weekly-plan.md)、[工程](../specs/desktop-weekly-plan-engineering.md)。现有 CPython3.14.10／Windows x64／标准 GIL及锁定依赖保持。

原 OpenCode A 续 `ses_ead8af71dffeJphI1NOWg4jZgI`，负责现有脚本构建与最终 Git；B续`ses_e72ecd5f9ffeYJaLRNypsdu5Pi`，仅写新`.github/workflows/windows11-weekly-validation.yml`及必要`.github/scripts/build-windows11-validation.ps1`；Command Go C续`8cf528de-8773-4a06-9cc5-31e96fab515f`做只读静态反例与交接审阅；D续`16cf76b5-ea0b-47f5-bc94-26147c9d3689`仅修`desktop/check_windows11_target.ps1`当前正向Python3.14.7为3.14.10，已停写。固定原模型／max，不fork／子代理。除此不获生产源码写权；新缺陷先固定证据再分配精确文件。Codex负责文档、独立核查和Git门禁，不另起业务实现者。参与者不是唯一写入者，不还原他方修改。本轮白名单取代工程§8上一源码片的在途分工。

## 构建与核查

1. 新物理根 `build/desktop-e14-weekly-win11-r01`；保留所有旧包／首失败／保护指纹，不复用旧 r03。沿用完整 onedir／windowed＋ZIP；私有报告与 freeze 在独立 TEMP 根，不进入程序分发目录。
2. 构建前确认路径合法、源码停写、0007迁移及周模块／模板／前端已入现有来源合同。冻结覆盖 Vite／PyInstaller／ZIP 全链，前后逐项相同，实际 build_id／SHA 与来源 commit 分开记录。
3. 只执行源码静态核查，不运行本机4551受阻候选 EXE／helper。真实读取 CArchive／PYZ、前端／模板／迁移、清单／ZIP和隐私，检查器必需项必须明确通过；旧源码／旧包／旧Word结果不移给新包。
4. 目标预检脚本以本轮交接副本完整字节 SHA 绑定；目标普通运行、保存重开、周确认／旧确认导出、备份恢复、新周Word逐页和教师反馈另列待验。新包身份及结果归本轮结果文档，步骤归本轮目标手册，旧 r03 记录保持历史身份。
5. GitHub工作流在现有桌面分支push触发新构建，使用Windows x64 runner及精确当前Python／Node；仅临时runner安装现有哈希锁和构建约束，不改本机／依赖。完整静态全部通过后上传最小交接制品，核实际运行与下载；不建tag／Release、不改main。GitHub与本机构建各自身份，不混用通过。若远端失败保留首失败，按原责任会话最小修复并重新审核提交。

## Git 门禁

仅原 OpenCode A按Codex核定具体路径／raw SHA／规范index blob／准确parent暂存后停下；Codex核cached集合、blob和write-tree后，才授予该parent／tree普通commit及既有分支push。不得add-all、amend、rebase／force、改main／默认分支／可见性、tag或Release；候选／数据／凭据／私有日志不入Git。

## 保持边界

另一台电脑尚未操作，目标结果和教师体验不能预填通过。微软拼音不重测，W6跨120秒睡眠不追测；旧无guard缺口、长根206、Win10／WPS／其它显示／干净机等保持原未验。不安装工具、升级依赖、运行真实AI／WebDAV、签名、安装更新、远控或公开发行；Q5/Q6周AI／材料不在本轮。
