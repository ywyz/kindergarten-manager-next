# Windows 11 白屏、并发首失败与 Word 注册调用补核

更新：2026-11-04。状态：限定测试修复经Codex独立审核通过，最终后端62项、桌面35项通过，允许按§5门禁普通提交推送。白屏原实例的渲染器已丢失，受控重开保留数据且正常退出；最初触发原因未证实，未新增自动恢复行为。Word当前功能正常，/r历史注册差异不可还原。前轮包身份、首次策略拦截、三次真实AI及保存／Word／备份结果见[目标机核查](desktop-weekly-ai-windows11-target-review.md)。不作完整产品验收结论。

## 1. 授权、来源与责任

用户明确授权原OpenCode会话和Command Go继续使用DeepSeek V4.1 Flash max，排查白屏及并发首失败、核查Word/r影响，保持系统保护不变；处理后继续测试，由Codex审核，通过后提交推送，交开发机接续。沿用`codex/desktop-v2-foundation`，开工HEAD与远端均为`7eb4b5ea859625de83fff073b01c6bb543e5cdf5`；开工12文件未提交补丁`c745f3cc…`及两份正式文档差异已保留，不覆盖原件。

原OpenCode`ses_e651729c9ffeG6mP7f6K1oat1I`／build／`opencode-go/deepseek-v4.1-flash#max`负责白屏生命周期诊断及必要修复。Command Go复用本机既有`b5a7810b…`会话，实际请求metadata为`deepseek/deepseek-v4.1-flash`／max，负责并发限定诊断。历史开发机C／D会话在本机不存在，没有假称恢复它们或fork。双方不派子代理，不改依赖／迁移／保护／Office注册，不签名或发行。

Command Go首试读取外部任务文件被工具权限拒绝，未执行源码改动；内联任务后仓库只读核查及隔离单项1/1通过，但源码`edit_file`与Git只读shell被其CLI权限拒绝。保留两个拒绝现场，不用CLI退出0冒称完成，也未以shell写源码绕过。Codex核定其自然停写后，将唯一`backend/tests/local/test_weekly_ai_adoption.py`写权转交原OpenCode；Command Go继续只读复核。未启用其要求的更宽CLI权限。Codex独占正式文档、Word影响独立核验及最终门禁，Git执行须后续具体文件／blob／parent／tree核准。

## 2. 白屏证据与受控重开

原候选仍为build`32a6d197-03c0-45ec-91fe-0b80d9528189`，EXE SHA `596f617ea9f3f40a952e3fb1dc7015509be5a85d4366efffd72ff3324cd7b2ef`。原进程身份／启动时间与前轮回执相同，消息泵仍响应，窗口只剩原生WindowsForms空子窗；没有关联WebView2浏览器／渲染子进程及其原生渲染窗口。Sky首次列窗超时、按规则2秒重试成功；遮挡状态截图一度捕获前台内容，重新选择并激活原窗后确认纯白与缺失WebView树，未把单幅截图当作全部证据。

限定事件回执记录07:04:41的Winsrv 10001：该应用试图否决关机。周边注销／关机失败是时间相关线索；未取得足以确定WebView2丢失的精确外因或与Word/r因果关系的证据。不以T09私有目录安全拒绝、分辨率变化或聊天中断直接解释外部进程消失。没有采集凭据内存dump、浏览器profile或无关资料。

现有[关闭协调器](../../desktop/d1_host_api.py)在页面通知失败后保持pending，30秒后取消并释放本次冻结；没有页面最终保存ack便不会销毁。原OpenCode私有反例核到pending→canceled、destroyed=0，重试生成新请求且仍不隐式允许；既有32项关闭及3项AI关闭屏障通过。Codex回读实际实现，认定这是当前保存保护合同内的拒绝，未发现独立可证的协调器缺陷；没有新增自动reload／自动退出／强杀或绕过保存保护的产品行为。渲染器丢失的产品恢复交互仍须另行核定，不写白屏已修复。

原白屏实例全部表和34受管文件在首失败后保持一致，3个task／execution／attempt均已成功。Codex保留一致性副本和进程／窗口证据，再核PID、启动时间、实际EXE路径及SHA，**仅外部终止该合成测试进程**；实得退出码`4294967295`（`0xFFFFFFFF`），不记正常关闭。没有全局kill、删锁、改保护或动原始合成源。

随后用同一EXE、原档案及同机凭据根普通启动，工作台正常显示；外部终止前／终止后／重开后／正常关闭后四阶段全部表及34受管文件完全相同，凭据密文行仅作不透明比较、未解密，任务与attempt仍3、无新增发送。该新进程正常关闭exit0。此为外部中止后已保存资料的恢复验证，不等于原故障自然恢复或异常页面的保存能力通过。

## 3. 并发测试首失败及最小修复

原60项首轮59通过／1失败、`ObjectDeletedError(LocalProfile)`及隔离复跑通过保持[原证据](desktop-weekly-ai-windows11-target-review.md#7-已授权t03来源修复与第二新候选)。`preview_adoption`的只读作用域最终rollback，使主Session里的`self.profile`过期；旧用例两个worker虽然各建Session，却在调用采用前读取`self.profile.id`，可能在工作线程通过主Session懒加载。

本轮只改上述测试文件：线程启动前捕获所需标识／版本／token；保留双线程Barrier和各自Session。增加线程确实终结、主Session在worker中没有ORM／事务活动、profile仍过期未加载、两结果相同且一新建一重放、一采用／一新稿及旧稿保留等断言。反向对照故意在worker读过期对象，实际观测主Session在该线程开始事务；这证明旧夹具危险路径，不宣称重现了最初ObjectDeletedError的精确概率交错。没有修改采用业务或用重试、串行化、sleep、skip消除失败。

实现者首轮追加断言误用了不存在的`current_content_id`，1失败／1通过，首日志保留；更正为真实`current_draft_id`后两个针对项通过。原OpenCode在文件SHA `11fe34e0…`下采用／备份33项、service46项通过，保留双线程的5次有界复跑均通过。Command Go同会话只读审核该快照无阻塞项，建议补充新稿总数断言。Codex核定原OpenCode追加“原数量＋1”，最终文件SHA `14f3642da02bfba4a247b00ad5153c2a2d7961818994d01c33776fff08a6ac92`，针对两项再通过。Codex独立回读最终diff并执行§5的完整相关范围；不把Command Go的早一版审阅或实现者33／46项冒称最终文件的独立验证。

## 4. Word /r 影响核验

微软明确说明`/r`会重新注册Word，并通过Office Setup更新注册表后退出。[官方参数说明](https://support.microsoft.com/en-us/office/lifecycle/command-line-switches-for-microsoft-office-products)。前轮一次误用/r是实际额外调用，不能当普通打开或声称无副作用。

没有调用前注册表基线，本轮未再次/r、regserver、Office修复／重装，也未改注册表、文件关联或Office安全配置。只读核当前Word为`16.0.20527.20112`，与前轮页检记录相同，签名Valid；App Paths、`.docx`／`.doc`、Word.Document打开命令、Word.Application.16／CLSID／LocalServer32共11个明确注册项结构与现安装路径一致。调用附近限定时间窗的相关事件查询成功、结果0；这不证明当时未修改注册表。

使用前轮合成Word的独立副本，通过明确`/n /q`普通打开，实际查看两页并正常退出exit0；又由现有默认DOCX关联正常打开Word并关闭。原文件及副本SHA保持`b8f41b8a…`，11个当前注册项跨本次功能复验不变。**当前注册结构、关联打开与文档功能限定通过；/r具体历史增删项仍不可判定，未回滚未知变化，也不宣称所有用户偏好保持原值。**

## 5. Codex独立验证与Git门禁

原OpenCode自然停写后，Codex固定393个源／资源／锁文件并独立执行相关范围，最终前后SHA一致；原12文件与构建批准逐文件SHA完全一致，组合补丁仍`c745f3cc7d6e52b9b5c986d8ee9ba7ecd767951e96b859ff9714dba078b9765d`。新增实现范围仅上述第13个测试文件，不改生产采用／关闭行为、迁移或依赖。原源码首轮59／1的失败记录保留，未覆盖旧日志。

| 独立核查 | 最终结果 |
| --- | --- |
| 后端相关范围 | **62通过，exit0，192.90秒**：来源变化service3、API14、采用17、周AI备份16、材料12。包含原失败用例和新增反向对照，保留52条既有弃用警告。 |
| 桌面关闭／AI屏障 | **35通过，exit0，3.62秒**：关闭32、屏障3。 |
| 源身份 | 393文件前后稳定；原12文件批准SHA保持；最终并发文件为上述14f3642d…。 |
| 验证环境 | 现有CPython3.14.10／Windows x64／标准GIL，独立短合成根，禁dotenv及外网，源码测试显式使用SQLAlchemy纯Python模式；冻结普通入口未使用该调试开关。 |
| Python守卫 | 两套日志均仅含atexit的`exit unknown`，无越界／网络记录；实际pytest退出0由独立进程回执及XML共同确认。该日志字段不作为退出成功证据，也不外推OS／原生进程隔离。 |
| 实际模型 | OpenCode导出核为原session／build／opencode-go Flash max、末次finish=stop；Command Go三次原生任务共14次model_request_end全部为Flash／max，首任务permission_denied、后两任务end_turn。 |
| 系统保护 | 09:46本机时区只读复核：SAC=1，8个策略名称／SHA与修复前完全一致；CI日志查询成功，当前候选路径事件0。未更改保护／注册／文件关联。 |

私有原始证据留测试机：两套独立日志／XML／源码前后清单，双方原生模型metadata与首拒绝，原白屏进程／事件／退出及四阶段一致性副本，Word当前注册／功能回执。公开仓库只收脱敏结论和审定源码，不收原日志、用户名路径、凭据／口令、SQLite、截图、Word或备份。原真实AI仍累计3次成功，本次补核新增0次；现有32a6d197…候选保持原“7eb4b5e＋12文件补丁”的构建身份，不因本次源码提交变成新CI包，未重建。

Codex结论：上述源码修复及限定验证**通过，无阻塞代码问题**。保留白屏精确触发原因、异常页面未保存资料及恢复交互设计、/r历史差异与前轮未验边界；这些均不写已修复或完整验收。通过后由原OpenCode按具体文件／Git规范化blob／parent核准清单只stage；Codex独立比对index后再核定tree及普通commit／push。禁止add-all、amend、rebase、force、改main／tag／Release或纳入私有证据；Git实际提交身份以分支历史及最终远端核对为准。

开发机接续见[唯一入口](../tasks/current.md)：先保留本地修改再快进核源；4551主系统保持源码验证边界，不启动候选／helper。白屏后续以受控合成复现和保存合同为起点，有证据的最小修复仍由原生指定模型实施、Codex独立审核；新增渲染恢复交互须先核定产品行为，不默认reload／退出或强杀。没有新增发行／签名／WebDAV／安装更新授权。
