# C5 v2 契约发布与 Windows 接续（2026-10-07）

结论：在已有用户授权及 [Windows 首阶段就绪报告](ai-slice1c-fixture-windows-stage1-result-2026-10-07.md)的基础上，协调者已向独立夹具发布 daily_lesson_split v2／默认 r9。只执行一次发布；C5 产品验收仍待 Windows 完成适配验证。

## 实际发布与复核

- 目标：`https://kg-next-ai-fixture.ywyz.tech`／`kg_next_ai1c_fixture`；原实例不是发布目标。
- 发布前只读 inspect：v1／r8；tfr_i5 个人版本2、based v1、accepted default8，六个 `AI1C-C5-v1-<字段名>` 与报告完全一致。
- 固定工具 SHA-256：`634f94d3cfb4ce0a6183a29c295dd82dd81838611cc63949c6639f38ac6ece47`。仅该发布子进程设置专用允许开关，expected contract=1、default=8。
- 工具返回 exit0、status=published：v1→v2、r8→r9。实际新增默认行时间为 **2026-10-07 20:25:17 Asia/Shanghai**，最终只读复核完成于20:26:33。
- v2 固定字段顺序：theme、objectives、key_points、difficult_points、process、acceptance_support；移除 preparation，新增 acceptance_support。完整默认 map 精确匹配工具配方，含合成说明后缀。
- 个人 head／version 两表发布前后规范化哈希相同，未替教师适配或初始化；其余六任务仍为v1。随后页面 GET 可能按正常产品流程更新适配状态，发布本身未推进个人 head。
- 临时与原域名 `/health` 均200，原 current 仍指向原部署 release。主密钥未切换，未发布v3，未调用供应商。

附加核验中，协调者先误将默认文字简化为不带说明后缀，后又使用了错误健康路径 `/api/health`（404）。两次均为提交后的只读检查问题；未重复发布。改按完整固定配方及真实 `/health` 路径复核后通过。首次尝试运行解释器时遗漏backend目录，命令未启动；更正后才进行只读基线核对和唯一一次发布。

## 证据及后续

服务器私密目录 `/opt/kindergarten-manager-next-ai-fixture/private` 保留 `c5-v1-before-publish.json`、`c5-v2-command-output.json`、`c5-v2-publish-manifest-20261007.json`。成功manifest只含去敏目标、版本、字段名、哈希和状态，交接至Windows既有logs目录。

Windows按 [C5 v2 接续提示词](ai-slice1c-fixture-windows-stage2-prompt-2026-10-07.md)执行，不重建v1、不重新初始化、不进入V1/U3或C7。原保存HTTP未捕获的缺口继续保留；新增适配阶段应独立记录真实HTTP和DOM。取得本阶段结果后再决定归档、恢复 B_contract 与下一案例交接。
