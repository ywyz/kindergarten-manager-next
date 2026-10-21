# 普通运行验证包整合已完成；停在真实AI／发布授权边界

2026-10-20用户授权将已验修复整合进普通运行验证包，直接调用OpenCode、仍用Go套餐DeepSeek V4.1 Flash；Codex独立核查，有问题继续交回，暂不调用应用真实AI或发布。本次范围现已完成，独有决定、失败与回修、未验边界已归入下列结果／核查，不保留过期实施提示词。

## 当前有效交付

- [OpenCode实现与回修结果](../bootstrap/desktop-d2-normal-package-result.md)；[Codex独立核查§6](../bootstrap/desktop-d2-normal-package-review.md#6-最终独立核查与交付结论)。N01构建路径保护／N02运行说明已回修关闭，无剩余本轮编码任务。
- 完整普通包：build/desktop-d2-normal-r01/package/KGNext-D2Verify/（182文件，不能只复制EXE）；EXE e843d11b38ff87fc4876313aad8a20cb60912ff73c61b1f35d908dae81a6ba5c，15,048,169字节；清单99ae429a998fdae01a187bf9c62a8ebedf718525b3c4b1ce3c612f72f0fdfbd2。说明与逐文件清单在同一构建根RUN.md／package_hashes.json。
- 独立前端typecheck／逻辑／60组件／81组件、196桌面、8项构建路径保护与仓外冻结130项通过；真实d1_main入口及54模块同源，新前端与已验R01一致。最终包字节不变；旧683文件数量／集合／hash保持。只改构建／验证脚本与针对性测试，没有业务／前端／迁移／依赖改动。
- 两轮直接OpenCode均CLI exit0；原会话ses_ead8af71dffeJphI1NOWg4jZgI新增42条assistant实际模型均opencode-go/deepseek-v4.1-flash#default，最终stop／succeeded。未另起实现者或子代理。

## 保持的边界与后续顺序

[W6收口与三项后续事件](../bootstrap/desktop-d2-w6-closeout.md)及[原人工记录](../bootstrap/desktop-d2-w6-manual-acceptance.md)继续有效。跨120秒睡眠不再验证，白屏等复发，额外任务用户倾向误点／保留观察；同类再现保留现场后再按机制处理，不重新追查，不把未验／未修写成通过。既有Word及人工确认不扩大为本新包重新人工验收。

普通包新Word逐页、真实供应商G17／质量与用量、完整教师确认、干净机器／Win10／WPS／其他DPI／发行仍未验。下一步可准备G17材料、供应商配置／用量上限／停止规则与结果表；任何实际应用真实AI调用须用户另行明确授权调用及用量边界。密钥由用户在应用填写，不写聊天或仓库，不自动重试结果不明请求。当前不调用真实AI，不发布，不启动D3历史／WebDAV、观察记录、新班级切换或安装发行。

继续codex/desktop-v2-foundation。上次Git检查点d24a1b7已提交推送；本轮新增变更尚未自动commit/push。OpenCode唯一写实现／测试／迁移／构建，Codex规划、核查、执行验证与Git管理；后续若需要修复沿用原会话与指定Go Flash，不另起实现者。保护默认教师库、全部旧包、原human／诊断根、Word与失败日志，自动验证只用独立合成库／LOCALAPPDATA并禁dotenv。原窗口历史PID不是当前状态；任何后续操作先核对真实进程和数据身份。
