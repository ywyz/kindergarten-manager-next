# Windows Codex 第二阶段提示词：C5 v2 适配

用户授权持续有效。托管者已核对你传回的v1就绪报告，并于2026-10-07 20:25:17 Asia/Shanghai只发布一次v2，默认r9。读取同目录 `ai-slice1c-fixture-c5-v2-publication-2026-10-07.md`、最新Windows交接、夹具方案及旧桌面提示词C5；本次实际状态优先于历史受阻描述。先读取既有私密logs中的 `c5-v2-publish-manifest-20261007.json`，确认status=published、目标库kg_next_ai1c_fixture、v2／r9。

只执行C5，使用本Windows会话已有浏览器工具。接续你交接的外置Edge页面（历史tab1378631857，以现场库存为准）；失效时在唯一夹具域名重新登录tfr_i5，不触碰其他用户标签。不重新初始化、重复发布或直接写库。不用API直调替代UI，CDP仅用于观察真实请求及必要的既有响应延迟能力。

1. 真实刷新并进入教案拆分，核验个人revision2／based v1、latest v2／default9、待适配；六份旧文字仍可见，接受／拒绝默认不可用。若现场不符，报告并停止依赖步骤，不自行复位。
2. 普通编辑一个旧based字段，例如theme改为 `AI1C-C5-v1-theme-ordinary`，点击普通保存并重读。仅改变字段提交，状态仍待适配；记录真实HTTP、实际个人revision和六份文字去向，不将普通保存当成完成适配。
3. 打开完整适配：theme等同名字段保留当前个人文字，acceptance_support预填本轮v2合成默认；preparation旧文字在只读区域可见。先纯预填关闭，不提交、不推进适配、不制造dirty；真实返回页面无未保存确认，再进入设置／任务继续。
4. 再打开适配，编辑theme为 `AI1C-C5-v2-theme-adapt`、acceptance_support为 `AI1C-C5-v2-acceptance_support`。关闭应保留草稿，返回设置外应有未保存确认；取消离开后两份草稿仍在，重开适配确认实际DOM内容。
5. 通过UI完成适配，提交完整最新v2六字段map及现场expected/target，移除的preparation不得混入map。成功后刷新读current／based v2／latest v2，六字段及合成文字持久。记录真实HTTP与个人版本演进。使用已有工具能力观察真实提交期间普通输入、放弃和重复写按钮禁用；若需要延迟真实响应，仅记录为前端时序辅助证据，不合成服务端成功，不强行赋值disabled控件。不能观察的子例如实标受阻或未执行。
6. 写去敏报告 `C:\Users\yw980\.codex\tmp\ai1abc-desktop-acceptance-20261005\logs\ai1c-c5-v2-result-20261007.md` 和证据清单，仓库可写时同步独立C5结果文档。逐子例记录通过／失败／受阻／未执行、真实DOM区域、HTTP状态和版本、截图路径；保留首阶段原保存HTTP未捕获事实。secret、cookie、token、密码、DSN和完整敏感请求不得输出。

发现失败保留现场并给最短复现，不修业务代码。完成后交回报告路径，等待托管者归档和恢复安排；暂不自行退出或关闭需要交接的测试页面，不执行V1/U3、不发布v3、不切主密钥、不调用供应商或启动其他切片。未完成子例不宣称全通过；不自行commit/push。
