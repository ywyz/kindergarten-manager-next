# 普通包已提交推送；G17方案已准备，真实调用未授权

2026-10-21用户要求：“把本轮修改提交并推送，然后准备G17真实AI验收方案，明确调用次数、用量上限和停止条件，暂不实际调用真实AI或发布”。普通包相关修改已完成提交与推送；本次只准备文档，没有真实供应商调用。

## 有效入口

- [G17验收方案](../bootstrap/desktop-d2-g17-acceptance-plan.md)：虚构材料、执行前就绪表、三类顺序、token／费用落实限制、停止规则与未执行结果表的唯一方案入口。
- 普通包提交2cafa4962c9cf132ce584c2ad96a96191d653713已推送origin/codex/desktop-v2-foundation。[独立核查§6–7](../bootstrap/desktop-d2-normal-package-review.md#6-最终独立核查与交付结论)及[OpenCode实现结果](../bootstrap/desktop-d2-normal-package-result.md)保留N01／N02关闭和实际证据；包仍为build/desktop-d2-normal-r01/package/KGNext-D2Verify/完整182文件、EXE e843d11b…，不重建／上传包。历史运行说明与清单仍在同一构建根RUN.md／package_hashes.json。
- 本次G17准备文档按本轮Git授权另作独立文档提交；实际提交／推送结果以Git记录为准，不为写入自身hash重复制造提交。

## 当前执行边界

G17建议为拆分／适龄／其他活动各一次，最多3次已发或可能已发请求；单次输入≤6,000、输出≤2,000，累计≤24,000 tokens，费用≤人民币1.00元。**均为待后续调用授权确认的建议，不构成本次消费授权。** 当前普通请求无输出token上限参数或总预算执行器；须落实方案中的供应商硬限额与可靠计量条件。软提醒、事后usage、提示词要求、120秒／1MiB均不能替代硬限额；无法落实则不发送，不擅自改实现或降级预算约束。

当前不启动普通业务窗口，不填真实密钥／配置，不发连通／模型／余额API，不创建真实AI任务，不发布。下一步仅在用户另行明确真实调用及用量边界后，先按方案就绪表检查所选供应商／模型和硬限额，再决定能否执行；需要实现改动时另作明确最小工作包，由原OpenCode同一Go套餐DeepSeek V4.1 Flash实施、Codex独立核查，不因本方案自动启动。

## 保护与既有结论

保持codex/desktop-v2-foundation；OpenCode唯一写实现、测试、迁移与构建脚本，Codex规划／审阅／验证／Git。保护默认教师库、全部旧包、human／诊断根、Word与失败证据；自动验证仅独立合成库／LOCALAPPDATA并禁dotenv，历史PID不是实际当前状态。

[W6收口与三项事件](../bootstrap/desktop-d2-w6-closeout.md)及[人工记录](../bootstrap/desktop-d2-w6-manual-acceptance.md)继续有效：跨120秒睡眠不再验证，白屏等复发，额外任务用户倾向误点／保留观察，不重启追查或记为已修复。G17／G18、普通包新Word逐页、干净机／Win10／WPS／其他DPI、D3／WebDAV、观察记录与安装发行均不因方案或Git推送变成通过或获实施授权。
