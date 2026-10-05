# AI 1A补修与补验：OpenCode交接（2026-10-04）

使用依据：[协调者审阅及设计决定](ai-slice1a-review-2026-10-04.md)。用户交给OpenCode执行以下正文时，授权仅覆盖1A定向补修和隔离自动验证。业务代码由OpenCode唯一写入，协调者负责设计及复审。

## 可直接复制的提示词

~~~text
你是kindergarten-manager-next业务代码唯一写入者OpenCode。1A首轮交付已完成，但协调者审阅未通过。本次实施1A定向补修及补验，不进入1B，不重新规划产品或架构。

先读AGENTS.md、1A设计清单v3、原始实施结果报告，以及docs/bootstrap/ai-slice1a-review-2026-10-04.md。后者R1–R7及§3为本次补修方案，具体落实v3原有契约；不允许为通过测试删去新增字段、弱化断言或把未来功能写成已验。

记录开工HEAD及git状态，保留全部已有代码／文档修改；不回退、不清理他人文件，不读.env或私密密钥，不复制旧项目、不新增Skill/MCP、不启动额外编码代理。协调者只负责设计和审阅，你按以下决定编码，不先交另一份待设计清单。

授权范围：
- 修改本轮1A新增的services、unit/integration测试及ai1a_guard；按R5修正尚未部署的20261003_ai1a_config_prompts新增迁移固定种子。必要内部helper可在本片services范围调整并报告。
- 不改已有I1–I4迁移、日／周／导出业务、API/UI、技术栈或Contract产品规则；不新增表或业务组件。
- 直接依赖和版本保持原样，不安装新依赖或下载Python。可用既有uv按锁检查／同步本项目.venv。
- 允许再次建立专用一次性mysql:8.4.11验证容器，只暴露127.0.0.1:13387；库白名单kindergarten_test_ai1a、kindergarten_test_ai1a_fresh。独立AI1A_TEST_ALLOW_DESTRUCTIVE=yes＋AI1A_TEST_DATABASE_URL，全程APP_DISABLE_DOTENV=1。guard在所有连接及Alembic子进程之前生效，不继承私人DATABASE_URL或主密钥。仅清理本次新建容器／卷／测试库，报告身份与清理，不复用或删除预存资源。

定向补修：

R1 真实入口和typed错误：
导入正确TASK_TYPES／FieldViolation，修正任务列表和服务非法输入NameError；处理ai_locks中未使用且引用未定义PromptDefaultVersion的helper，删除或修正均须保证不残留名不副实的locked函数。为get_task_types、真实list_tasks以及空patch／未知字段／非法版本等服务入口补测试，不能只测registry。

R2 字段适配采用相应的已发布contract：
把任务白名单与指导字段集校验分开。先在锁内重查目标contract，再用其guidance_fields验证完整映射或选定字段：
- initialize、adapt、update_default用最新目标contract；
- accept先检查个人based／当前／目标default契约一致，再按该contract验证选定字段及完整新映射；
- personal_edit按该个人版本的based contract验证，不改其结构或默补新字段。与v3一致保留文字，AI就绪仍由当前契约兼容性判定。
字符串严格、单字段8000字符、未知／缺失字段拒绝；shape、字段名类型的无副作用检查可提前，但不得在访问数据库前用v1字段集拒绝合法v2提交。adapt的旧目标冲突在锁内复核并完整回滚。
测试夹具真正给guidance_fields新增一个v1不存在的字段并发布匹配默认；验证初始化、适配、个人编辑和管理员默认更新；再发布含另一新字段的v3，旧adapt拒绝。不能修改运行时TASK_REGISTRY冒充测试或用v1已有preparation假装新字段。

R3 就绪必须认证当前密文：
_evaluate_ready有secret时，按行account/version/key_id调用现有认证解密；密钥缺失、格式错误、key_id不同、主密钥错误、密文或AAD篡改均ready=false／DECRYPT_UNAVAILABLE。无secret仍MISSING_SECRET。
仅认证校验，脱敏返回对象不含plaintext；不缓存明文，不因失败改head或secret。正常有效配置仍ready=true；清除在主密钥不可用时仍能执行。用未入库合成行的单元测试和真实行测试补验，不能只验证load_material格式。

R4 内部对象不能被通用编码暴露secret：
DecryptedConfig改为非dataclass内部类型，使用__slots__且无__dict__／iter字段出口；secret以已有SecretStr封装，通过明确方法取值供授权内部调用。repr／pickle／copy仍拒绝或脱敏，不把原始secret放到公共映射。
对dataclasses.asdict、FastAPI jsonable_encoder、常规JSON／vars转换增加“拒绝或结果无合成明文”的断言；AiConfigView正常序列化且不含secret。所有测试只用合成材料，不打印secret；当前无API不构成跳过安全边界的理由。

R5 导出的schema必须与运行时相符：
必填字段不要设默认；枚举使用Literal或等价的可导出声明。拆分六字段、周游戏五字段的required准确导出；group_kind/context_kind/target_slot/origin包含enum。可省略但不允许显式null的日活动字段，在导出schema准确表达；未知字段递归forbid。
材料item的text/origin/evidence_refs是必需字段，suggested显式给[]，extracted仍非空证据。默认列表用工厂，避免共享状态。保持v3业务语义，不改变手工保存schema。
更新本轮新增迁移固定字面量种子，仍禁止import运行时registry；保持revision和七表不变，比较JSON内容。不得改历史I1–I4迁移。若实际发现本片曾部署到共享持久环境，停下报告协调者，不擅自重写那里的迁移记录，也不连接远程查证。

R6 当前指针与关联版本读取：
当前head被locking read锁定后，写路径读取其指向的配置／个人版本也用current locking read＋populate_existing，不能普通快照读取新指针指向的行。对相应函数区分“展示读”与“写事务current读”参数或入口。
管理员_default读取的share=False分支仍须FOR UPDATE／等价locking read，不可退成普通读；共享分支FOR SHARE。保持account→session→head→固定contract v1锚点锁序，不反向取锁。内部解析不自行commit调用方事务。
真MySQL测试：Session先读建REPEATABLE READ快照，另一连接提交新配置／个人版本／默认，再让旧Session执行保留secret更新、清除、个人编辑／接受、管理员默认发布。正确新expected成功／旧expected冲突；不得AssertionError、NoResultFound或重复revision IntegrityError。断言版本/head/审计真实结果。

R7 补齐既定迁移与约束证据：
从I4 head升级前，通过既有服务创建日内容、周草稿／来源及至少一份确认快照；在专用库里比较升级前后旧表完整行及JSON，不能仅比三个列／计数。空库升级也重新验证。
CHECK负例先建立有效账号和被引用版本，满足其他FK／唯一条件，再单独违反目标CHECK，核对数据库错误码／约束名。新增“nacc2不存在”导致FK报错不能充当适配CHECK证明。
contract并发分别验证发布先（旧适配回滚）／适配先（发布等待后推进），使用真实新增字段；拒绝先／接受先语义不变。新增测试应先针对当前缺陷确认失败，再补修转绿，报告实际证据。

局部一致性：
- reject的幂等判定移到目标默认存在及契约兼容核对之后，保持身份／expected先检查，无重复事件。
- 离线URL畸形解析均映射为现有typed输入错误，空query／fragment分隔符也拒绝；不实现DNS、代理、连接或transport。
- 测试先加载AI1A guard，合成日内容使用本片纯夹具，避免先import带I5 guard的support模块。guard/Alembic异常不拼完整URL或继承连接凭证，失败证据只显示脱敏目标和错误类别。
- 动态来源helper不作为本片业务采用验收，不扩游戏分类／去重／材料采用业务。

验证与交付：
1. 定向失败用例转绿后复跑全量backend/tests/unit，APP_DISABLE_DOTENV=1；不启动服务。不把578旧单元通过当作新缺陷已修复。
2. 专用guard下跑新增及原1A真实MySQL验证，重新核对迁移heads/current、七表约束、事务、并发和手工降级。无主密钥／错误主密钥下手工日周及Word导出定向证据保留。
3. uv lock --check、git diff --check；检查无业务范围扩展，测试资源清理完成。Docker／专用端口不可用时不改宿主环境，完成独立部分并报告真实MySQL阻塞，不宣称收口。
4. 新增docs/bootstrap/ai-slice1a-repair-result-2026-10-04.md，按R1–R7逐项记录文件／实际失败与通过证据／命令／测试数量／迁移head／锁变化／资源清理／未执行项。保留原报告历史结论，并注明它已被本次审阅发现缺口，不重写成首轮就正确。报告不含密钥、凭证或DSN。

禁止进入1B/1C、worker、transport、候选采用、材料闭环、secret清理、供应商调用、部署、SSH、commit/push。修复交付后停止等待协调者复审。
~~~
