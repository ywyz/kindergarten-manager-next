# MySQL 持久AI任务实施规格

状态：2026-10-03工程规格收敛；只继承[ADR 0002](../adr/0002-background-tasks-and-versions.md)和现有I3／I4版本规则，不新增技术组件，不授权worker启动或部署。依赖[AI Service](ai-service-implementation.md)、[提示词](prompts-implementation.md)、[材料](weekly-materials-implementation.md)及[实施索引](ai-capabilities-implementation.md)。

## 1. 当前差距与责任

`weekly_plan_sync_states`目前是I3同事务写入的待确认投影，**不是任务表**。I4显式refresh／save／confirm消费来源，owner_id当前等于creator_id，接管未实现。后续需扩入持久登记、worker、候选与交接，不能把现有pending_projection当作AI排队／自动生成完成。

一个API进程＋一个独立Python工作进程，MySQL 8.4／InnoDB短事务协调，systemd管理。不用Redis、Celery、内存后台任务或浏览器维持执行。首个工程并发上限为1个出站调用；30人可提交并排队，吞吐／容量仍须验证，不承诺30个同时出站。

任务持久化不承诺外部供应商恰好一次。任务与网络结果不明状态必须对教师可见。

## 2. 模型与唯一性

工程方案新增：

- `ai_task_heads`：唯一(scope_kind, scope_id, task_family)，pending_generation、running_execution_id、desired_source_hash、not_before、暂停原因、generation单调序号。周生成family可分游戏／栏目／主题／材料；同一个日计划任务按task_type合并未开始请求。
- `ai_task_executions`：head＋generation唯一，execution_id、状态、claim_token、lease_until、owner_epoch、操作者／计费者、启动来源／草稿版本hash、input_snapshot_ref、实际配置／提示词版本、attempt数、结果候选ref／脱敏错误。
- `ai_task_attempts`：execution＋attempt唯一、send_marker时间、响应分类、调用记录ref；发送标记先持久提交，网络在事务外。

head最多一个running，最多一个可合并pending；running期间再次触发只更新后继pending，不能改运行输入。数据库唯一键、复合FK和条件更新保障身份，不能只靠Python锁。候选正文及业务输入快照归日／周模块；任务只存其引用／hash，AI日志不复制正文。候选落库与执行成功同事务并以execution唯一约束防重复写。

## 3. 登记、30秒合并和立即更新

日计划业务保存、同步投影与受影响周task head登记同一事务提交，失败全部回滚。保留I3／I4共用班级锁与既定业务锁序，task相关锁追加在现有业务／sync锁之后，不从任务锁反向拿业务锁。

每次相关保存更新desired_source_hash及generation，`not_before = 最后一次相关保存UTC时间＋30秒`。后续pending合并到最新完整来源，不排每份保存各自出站。保存响应立即带待更新信息，不等待网络；确定性日期栏目更新到待确认投影，worker短事务消费投影到新待确认草稿，保留人工override；不能原地改已确认快照。

没有真实周计划／负责人时，只登记该班学期周的待更新意图，不自动创建计划或猜负责人；创建周计划后绑定并消费当时最新来源。无配置／未适配可保存投影和pending但暂停AI。周计划自身草稿改变不会重置“日保存30秒”成隐式无限等待；材料依据变化另按材料触发规则处理。

负责人“立即更新”将对应pending的not_before推进到当前时间，仍由worker领取、重新校验权限／适配；不能在HTTP请求中直接发网络。运行中的旧任务不加速、不换来源；有新来源则保留后继pending。没有新来源时立即更新不得重复正在运行的同一generation。

## 4. 状态及领取

| 状态 | 含义与恢复 |
| --- | --- |
| `pending` | 未开始／合并等待，重启可恢复 |
| `claimed` | 短事务已领取并钉住输入，未持久send_marker；租约到期可安全重新领取 |
| `dispatching` | send_marker已提交、可能发送；中断后进入outcome_unknown，不能猜未发送 |
| `retry_wait` | 仅明确未处理的临时失败，按AI Service有限次数／间隔 |
| `succeeded` | 有校验后候选关联，仍不代表已采用／确认 |
| `failed` | 结构错误或有限重试耗尽；已有计划仍可手工编辑导出 |
| `paused` | 当前配置、适配、权限、交接等不满足；修正后受控恢复 |
| `outcome_unknown` | 可能已发但无已提交结果；无自动重发，可明确手动重试且提示费用风险 |
| `obsolete` | 来源／维护代际已推进，不能作为最新候选；有新pending则处理新代 |

worker非锁定扫描到期head，只用读取结果定位。领取短事务先校验／锁定对应身份和班级业务前缀，再按I4次序读取真实来源／草稿，最后锁task head条件领取、建立execution、钉住配置／适配指导和输入引用；锁冲突跳过本轮，不能保持task锁去等待业务锁。轮询工程初值1秒，claim lease60秒、heartbeat10秒，均用DB UTC时间。网络超时120秒期间heartbeat续租，不把“调用比lease长”直接当新任务。

不要求`SKIP LOCKED`读取业务数据，业务一致性读取遵循原锁协议。[MySQL 8.4官方说明](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html)将跳过锁行适用于队列式场景，不能拿不完整来源集合生成计划。本项目选择以上domain前缀后条件领取方案。

新增config／prompt当前指针锁放在业务／sync锁之后、task锁之前，多账号按id升序、多task_type按固定registry序；保存配置／指导的事务沿account／交互session→自身指针，个人指导写入随后拿对应contract v1固定锚点FOR SHARE，发布默认及协议拿该锚点FOR UPDATE；最新契约使用locking read。锚点属于提示词指针锁区域，在task锁之前，不反向取得班级／计划锁。细节见[1A定稿§7](../bootstrap/ai-slice1a-implementation-checklist-2026-10-03.md)。交接／恢复同序，heartbeat仅更新task，不持task锁调用业务方法。开工时把实际新增锁逐一映射到此顺序并做真实MySQL竞争验证。

## 5. 发送窗口和结果写入

1. 领取提交后准备网络连接；发送前短事务再次核定claim token、租约、账号／负责人epoch、配置／提示词引用以及来源仍允许本次启动；变动则不发旧调用。
2. 写入attempt的send_marker并提交，随后发送。标记到实际send间崩溃也视为可能发送，宁可提示人工处理，不自动赌重发。账户变动检查与外部发送不可构成跨系统原子事务；只有仍有效的执行许可才能新发，已经发出的请求可能继续计费。
3. 响应到达先做结构与业务校验，再新短事务按domain→task锁序重查token、owner_epoch和启动来源／所选游戏／草稿相关输入hash，记录候选与执行状态。
4. token失效的旧进程不得写结果；同一execution重复回调最多一份候选。启动来源改变的结果记录obsolete／历史依据，不进入“最新可采用”指针；旧任务完成不清除新pending、不把projection标成已消费最新来源。
5. 新候选不覆盖当前人工编辑／已确认版本；采用端仍校验expected_draft_version与当前来源。UI输入基线独立，候选通知不重基dirty表单。

发送前配置被轮换时，已经claimed执行按启动版本；待执行最新版本的规则不将claimed改成pending。权限或负责人撤销时即使配置被钉住也不能继续新发。

## 6. 重启、不明结果和手动重试

启动扫描过期执行：claimed且无send_marker可恢复pending；任何可能发送且无已提交结果进入outcome_unknown；已提交候选保持succeeded。retry_wait只有具明确未处理证据才恢复；不能简单把所有running恢复pending。

手动重试必须显示“先前请求可能已处理，重试可能重复计费”，显式提交`ack_possible_duplicate_charge=true`与expected_execution_id。新建generation／execution、用当前来源和最新有效配置／提示词，旧execution保留。相同client_request_id重传不得登记第二份；body不一致返回409。若来源已经变动且另有最新pending，关联该最新generation，不额外并行补发旧请求。

配置修复或完成适配可解除同原因暂停，使用最新有效配置继续未开始任务；outcome_unknown不因保存设置恢复自动发送。其他暂停原因仍须检查，不能把“配置好了”当作负责人有效。

## 7. 交接与权限

采用owner_epoch标识维护授权代际，不改creator。负责人调班／停用后暂停新发，取消旧claim执行许可、保留已发送的真实调用记录和原确认。管理员指定有效同班教师，接管待接受；接管者明确接受后推进epoch、owner_id切换，恢复最新pending并用接管者个人配置／提示词。拒绝／未接受不自动恢复。

拟定最小指定／接受API，均expected_owner_epoch防竞态；管理员不能替接管者接受或确认。API和worker共享“自动执行权限”判定，worker不要求负责人在线session；交互提交／采用／确认仍验证登录会话。实际发送与权限撤销竞争边界如§5，不能声称可撤回已发供应商请求。

删除／恢复、调班停用及完整接管是首版必要后续能力，当前I1–I4未实现的入口不能当已有依赖；实现切片明确接入。未交付接管流程的worker不得对无有效原负责人自动恢复。

## 8. API、UI与状态分离

拟定`POST /api/daily-plans/{id}/ai-tasks`、`POST /api/weekly-plans/{id}/ai-tasks`；输入task_type、expected业务版本、client_request_id，不接收billing_account_id／任意来源正文。返回202 task_id／generation／状态／not_before。材料上下文例外只允许服务器校验的已保存选择或不可变游戏候选ref。

`GET /api/ai-tasks/{id}`返回进度／原因、启动版本、候选ref和能否重试；`POST .../{id}/retry`处理明确重试。教师只读符合计划权限的脱敏状态，候选操作权限由业务模块重查，不因可看任务取得编辑权；配置和个人指导全文不随同班任务暴露。

页面分别显示任务等待／执行／失败／不明、来源最新与否、内容缺项、已确认版本。支持看到后台新候选后显式查看采用，不自动刷新覆盖dirty输入。历史确认导出按钮保留，按实际变化显示现有警示；AI失败不把其禁用。

## 9. 必须验证

- 同事务保存／登记失败回滚；密集30秒合并；立即更新和运行后继，重启pending恢复。
- 两worker误启动也无法重复领取／候选写入；token过期、heartbeat、kill在领取／marker前后／响应后／提交前后各窗口；不明结果零自动重发。
- 真实MySQL并发：沿用class串行与weekly→daily→sync→task锁序，旧结果不覆盖新来源，旧完成不清pending，保存不等待网络事务。
- 配置／指导排队与执行版本、适配暂停、停用／调班／待接受／接管epoch；用量身份正确，无借用密钥。
- 候选通知不重基dirty表单，采用／确认冲突保留输入；已确认版本可导出，不混入新候选。

故障注入必须有真实进程中断与数据库状态证据；模拟供应商可证明协议和恢复，不证明真实AI质量。自动测试、实际worker、真实调用、浏览器采用、Word验收分别记录。
