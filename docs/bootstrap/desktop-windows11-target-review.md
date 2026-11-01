# Windows 11 目标机独立测试记录

日期：2026-11-01。设备角色：目标 1（本轮实际操作的电脑）。Codex 独立执行；仅使用新建的合成数据、凭据和输出根。后端完整本地回归及原失败项定向复验均已结束；首轮失败、后续通过、权限受阻和未验项目分别记录，不能据此宣布整体验收通过。

## 1. 提示词、源码和候选身份

本地原检出为 `main`，HEAD `e836726f008676fc603a7b4cb058e5d96cafe60b`。开工时只读查询远端分支，执行提示词在 `codex/desktop-v2-foundation`，当时 HEAD 为 `2a4694893a083e32ba6203bfee6dbd83f890f02e`，提交时间 2026-10-31 23:55:05 +08:00，比 main 多三个提交；据其目标机预检和普通使用验收范围开始本轮，不能继续按 main 的旧“备份尚未实现”提示词判断。

测试期间曾查询到文档提交 `d6de14cb85040e5e68e3eab36b6d34fd5c927f8b`（2026-11-01 10:18:41 +08:00），执行提示词仍在同一桌面分支，`current.md` blob 为 `25d8b312b47d46f82808fadb7e37c9ba9728db66`。该版新增周计划＋明暗模式后续交接，保留本轮 r03 固定包完整身份／目标测试步骤。`2a46948..d6de14c` 的 24 项变化均为 Markdown；`backend/`、`desktop/`、`frontend/` 无差异。用户随后说明开发机已进入周计划开发，本轮停止轮询远端；受测源码仍精确保持 2a46948。后续开发提交不属于本报告受测身份，不据旧提示词描述开发机当前实施状态，也不将本次结果写成周计划／明暗模式已经通过。

在独立 detached worktree 检出上述精确提交，未切换、重置或提交原 main，未建立新的开发分支。首次 Git 状态曾显示 279 项行尾差异；忽略行尾后没有内容差异，后续 Git 状态刷新为 clean，未执行还原或行尾改写。

| 项目 | 本轮实际核对 |
| --- | --- |
| 候选 ZIP | `KGNext-E14-win11-r01.zip`，43,963,980 bytes |
| ZIP SHA-256 | `0a1b9c0b55612de889e621f70ed1374d8e792d3755d9fce1eadf17b7b6532470` |
| build_id | `5babc817-5b2a-466b-b382-36cffa02cace` |
| source freeze 身份 | `e1bbc5b01a1b55efece4a45089dc22f9e34fc872908bbb9c261aea85d0c03208`，仅核候选清单身份；未拿本机新环境重跑原构建 freeze |
| 数据库 revision | `20261025_0006_local_game_observations` |
| 主 EXE SHA-256 | `bb9214c2976aba96393740eee1aacb7727487aa294529849e4fe6a1cd989e9c3` |
| 实际交接 PS1 SHA-256 | `d7cdb39576a83ad76c71490b7416fa47e41f312acd8b7f1d8ca67bbc5ed1caaf` |

用户分别提供实际 ZIP 和另带的 PS1 路径，均与已审核身份一致。仓库检出脚本的原字节 SHA 不同：LF Git blob 为 `4b731ee70cdd74250f5e929625926a4ed8b7cf727e7a56fde7101201b086ff32`，CRLF 检出为 `2e76015457ab3b138a354d174faaca0a0708183bdfed722a8afce45d407e60d8`。首次按文档核仓库检出脚本，身份检查 exit 1，未执行该副本。随后用户提供的原脚本为 61,902 bytes、977 个 LF／其中 11 个 CRLF；将 CRLF 统一成 LF 后，与 Git blob 完全相同。最终执行的是 SHA 完全匹配的原交接脚本，没有替换预期 SHA 或绕过校验。

## 2. 本机只读预检和依赖

Windows 11 专业版，10.0.26300，原生 AMD64，普通权限。WebView2 Runtime `156.0.4314.58`。SAC 只读值为 1（enforce），可读的 WDAC 活跃策略文件 8 个；未改变策略、来源标记或信任设置。默认业务和凭据目录在开工时均不存在。

实际 PS7 `7.6.5` 执行交接脚本：**49 项，exit 0，失败 0、未知 0**。实际 107 个 PE 的签名为 **76 Valid、31 NotSigned**，主 EXE 为 NotSigned。另在本机独立核 ZIP 的 193 条目、190 产品文件、192 条 SUMS、每文件大小及 SHA、构建身份和 EXE AMD64 架构，全部匹配；核定 ZIP SHA 后才展开到新根，再逐文件复核解压副本。没有将这些检查称为原 54／59 项构建静态核查的重跑。

PS7 和 Windows PS5.1 parser 均为 0 errors／27 functions；本轮 PS5.1 没有执行脚本，不能标作运行通过。PS7 的执行策略实际为 RemoteSigned；PS5.1 各策略范围 Undefined，未改变设置。Word 已安装，实际文件版本 `16.0.20527.20088`。

本机起初没有项目 Python 依赖和前端 node_modules。用户随后明确授权自行安装缺少环境，pip 使用指定 CERNET 镜像。本轮按原 lock、`--require-hashes`、固定构建约束和仅许可的 proxy-tools 源码构建安装，没有升级项目依赖；两次安装和 `pip check` 均 exit 0。第一次环境位于检出根 `.venv-d1`，发现部分检查依赖约定路径后，在同一独立检出下补建 `desktop/.venv-d1`，首轮环境和日志保留。

前端 `npm ci` exit 0。首次 npm.cmd 使用了本机预装 Node 27 alpha 并给出 npm 引擎警告；实际回归、typecheck 和构建均显式使用已有 Node `24.19.0`，没有改全局 Node。依赖和产物都留在独立检出／测试根。

后端长回归期间另在证据根内的独立诊断 venv，通过同一镜像安装 `py-spy 0.4.2`。普通权限只读采样成功：先看到观察历史跨进程测试在等待 worker 通信，后看到观察模型测试初始化中执行 Alembic 迁移模块编译，证明进程继续推进；没有注入代码、修改项目依赖或终止测试。pytest 输出有缓冲，不能只按进度行停留时间认定挂起。

## 3. 自动验证及首次失败

| 项目 | 本轮结果 |
| --- | --- |
| Python 源码语法 | 222 个本地／桌面相关受跟踪 Python 文件解析成功；仅语法检查 |
| 前端完整 `test:d1` | exit 0：pure logic、组件 60、W5 94、历史 22、更新 14、观察 62、备份 adapter 9 groups、备份 UI 20 |
| 前端 typecheck／build:d1 | 均 exit 0；构建存在大 chunk／插件耗时提示，未当作失败 |
| desktop 首轮 | **485 passed、7 failed、1 skipped，436.70s，exit 1**；2 条弃用警告。跳过为 `test_archive_module_scope_covers_host_and_same_origin`：“原验证包不存在” |
| desktop 定位复验 | 原失败中 6 项各在针对性复验通过；跨轮累计 **491 项通过、1 项权限夹具受阻、1 项跳过**。保留首轮结果，不声称完整单轮 493 passed |
| local 后端完整回归 | **836 passed、12 failed、33 warnings，4317.47s，exit 1**；共 848 项，无 skipped／error |
| local 后端定向复验 | 原 12 个失败 nodeid 全部复验：**12 passed，30.12s，exit 0**。使用约定 `desktop/.venv-d1`、同一依赖 lock；没有改代码、测试或放宽时限。跨轮 848 项均有通过证据，不等于 848 项单轮全通过 |

桌面首失败的核对和处理：

| 首失败 | 定位和复验 |
| --- | --- |
| `test_build_identity_and_package_info_are_portable` | 检查器从约定 `desktop/.venv-d1` 读取 Pillow；首轮环境误放在检出根。补齐约定环境后通过。 |
| 两个 privacy／SBOM 用例 | 校验器同样读取约定环境中的已安装上游 SBOM；补齐环境后，与上项合计 **3 passed，4.08s，exit 0**。 |
| 两个 U2 真实合成进程用例 | fixture 使用 `frontend_dir=None`，默认构建目录不存在。显式提供本轮已成功构建的 `KGM_D1_FRONTEND_DIR` 后 **2 passed，68.85s，exit 0**；同源源码无改动。 |
| `test_connection_close_download_deadline` | 首轮在 metadata check 已到 0.1s 总时限，未到其目标下载阶段。单项复验 **1 passed，1.37s，exit 0**；并发负载是可能因素，不宣称已证明唯一根因。 |
| `test_report_path_guard_rejects_raw_parent_and_reparse` | `symlink_to` 在本机普通权限下报 WinError 1314，夹具未建成；仍记受阻。未开启开发者模式、管理员重试或改系统策略。另建自有 junction 独立反例，两验证器的 raw `..`、reparse 输入／报告路径合计 **10 项断言通过，报告写入 0**；不是原 symlink 用例通过。 |

首轮数据库／HTTP 故障替身中另出现 ConnectionAbortedError 输出，须结合最终 pytest 结果判断，不仅凭日志文字宣布应用错误。原始输出和 JUnit 保留，公开记录不放私有路径或原始数据。

后端首轮 12 项失败的直接证据及复验范围：

| 分组／原失败范围 | 首轮直接证据 |
| --- | --- |
| `LateAndDegradationTests::test_late_response_after_deadline_rejected`，1 项 | 等待 30s 后末态仍为 `retry_wait`；runtime meta 的 `processing_certainty=not_sent`。没有到达预期的已发送后 `outcome_unknown`。测试将总尝试预算设为 600ms，包含 worker 启动及调度；不能仅据短预算认定负载是根因。 |
| `test_observation_ai.py` 的 Review 4 项／PinnedConfig 2 项，共 6 项 | 全部在 `_run_generate → _wait_status(25s)` 失败，末态 `claimed`、reason=None；尚未进入缺图、receipt replay、rewrite、同 token 采用或候选 hash 等标题所指的业务断言。 |
| `ObservationAiRealTransportTests::test_observation_attempt_uses_vision_budget_and_unknown_after_deadline`，1 项 | 测试总预算为 1500ms；等待 15s 后末态仍为 `retry_wait`、reason=None，没有到达预期终态。 |
| `VisionHeaderTests` 的 fake daily header／invalid header only／without header，3 项 | `exitcode == 0` 断言均已通过，但 result=None；5s 接收窗口没有取得可解码结果。没有 worker 自然非零退出的证据。 |
| `VisionCapacityTests::test_old_text_frame_above_one_mib_is_not_received`，1 项 | join 5s 后 `alive=True`，随后测试主动终止子进程；不能写成 worker 自然崩溃。 |

复验的 12 个 nodeid 与首轮失败集合逐一一致，均按原时限通过。首轮没有提供业务内容错值、worker 自然非零退出或子进程异常栈；33 条 warning 均为 SQLite 默认 datetime adapter 弃用提示。现有证据可定位到任务终态／IPC 等待阶段，但尚不足以证明负载、启动耗时、环境路径或其他因素是唯一根因；复验通过不抹去首失败，也不宣称相关实现已修复。

## 4. 冻结候选普通界面：实际闭环

普通入口使用显式独立 data／credential 根，没有 selftest、桥接替身或直接改库建业务。首次页正常打开，合成教师、班级、长园所名和学期建档成功。没有配置真实 AI，未触发 AI 按钮或供应商请求。

1. 从日历新建日计划 A，填写主题和多行过程，保存 v2；离开后重开内容一致。
2. 从普通入口建立公共／室内／户外三类观察，填写合成正文；户外含 18 段长文。实际原生选图先取消，再导入自制横竖图片。合计 3 原图、6 衍生图；填写照片说明，并用前移调整顺序。保存／导出形成 7 个观察历史版本。
3. 从设置 UI 分别创建明文和加密完整备份；明文有独立确认，选择加密但未填口令时“开始创建”禁用。两包均显示“已完成并校验”。
4. 在另一套独立源码 Runtime 中核对实际 UI 备份。两包的 42 张表（41 业务表＋迁移版本表）与 A 逐字段完全一致；加密包 9 个图片文件与 A 的字节 SHA 全一致。校验进程安装了拒绝网络连接的替身，attempts 0；仅代表此独立校验进程，不冒称冻结程序 OS 抓包。
5. 将日计划改为 B，通过离开协调保存 v3；只读确认已保存的 JSON 正文有 B 标记。在自有测试根内移走外部合成照片原件，不动受管图片。
6. UI 选择加密 A，错误口令显示“密码不正确，请重新输入”；42 张表和 9 个受管资源仍与 B 全一致。正确口令后完整预览，取消显示“当前档案未更改”；再次比对仍与 B 全一致。
7. 再次校验加密 A，明确确认替换。自动生成恢复前保护包，新窗口正常出现并显示保护包位置。恢复后 42 张表与 A 完全一致、9 个受管资源字节一致，integrity_check=ok、FK=0；恢复本身没有增加业务内容版本。
8. 在恢复后的新窗口编辑为 A2，不先点保存而正常关闭；关闭协调保存了 A2。确认旧进程完全退出后，同一 EXE、同一合成两根启动全新进程；UI 显示 A2／v3，历史 v1／v2／v3 可查看。两次自动激活窗口超时后暂停输入，用户确认窗口正常并手动切前台；同时只读 Responding=true、工作台已加载。后续 Word 补测前同类自动激活再次失败两次，用户再次确认正常并切前台后继续；合计 4 次，均按恢复规则暂停／交回操作。此项记自动化激活异常，没有写成应用卡死或已修复。
9. 从普通 UI 校验并恢复步骤 7 的明文保护包，找回 B。新窗口和恢复完成提示出现；42 张表、9 个受管资源再次与 B 完全一致，integrity_check=ok、FK=0。第二份保护包与恢复前 A2 逐字段／字节一致；两份保护包均仍保留。
10. 恢复后打开观察，照片数量、前后顺序和说明保持；实际原生另存为取消后显示未写入，明确选择同一固定预览重试并成功保存新的 Word。与恢复前对应 Word 的全部 ZIP 成员及整体 SHA 完全一致。
11. 补齐 Word 矩阵期间，通过普通 UI 加入三图／五图，编辑独有目标标记形成 v11，并从日历另建第二日长文计划、明确保存 v2。这些是恢复一致性核对之后的新业务编辑，不把最终活动库继续说成逐字段未变的 B。
12. 正常退出后，用另一套此前不存在的 data／credential 根启动同一 EXE；首次页不填写临时档案，直接进入恢复。先选择明文 A 的独立末字节损坏副本，UI 拒绝并提示档案未变；42 表逐字段仍等于空档案基准。随后直接校验／预览／确认恢复有效明文 A，新窗口显示完整保护包位置；42 表和 9 资源与 A 完全一致，integrity=ok、FK=0。空档案保护包独立校验与恢复前 42 表完全一致，资源清单为空，710,455 bytes，SHA `95c00304635929d01c4cbc6d5851597e89faf93cb34ee6e335b222deee30ee6c`，仍保留。空基准含迁移版本和 9 个内置提示词包，无教师档案。独立探针首次错误地统计了 staging 中的 manifest／DB／WAL，修正为 `manifest.resources` 后资源数为 0；该探针错误没有记为应用缺陷。证据 `first-bad-package-preserves-empty.json`、`first-page-direct-restore-check.json`。

只读逐字段／资源核对均使用显式本轮合成 DB 的只读连接，不对真实体验库做恢复或清理。A／B／A2 的完整本地核对数据及故障现场私下保留。

## 5. Word 实际范围

| 样例 | 实际结果 |
| --- | --- |
| W1 单日日计划、可选缺项 | 冻结 UI 选“当前日期”，确认 11 个缺项保持为空；原生另存为成功。Word 实际 2 页，第二页为非空续表，逐页未见裁切或异常空页。 |
| W2 两日日计划、长正文／长园所 | 第二日从日历新建，填写主题和 20 段过程，明确保存 v2；周范围实际包含 11-02／11-03 两日。Word 实际 6 页，两份起始页 1／3，逐页核对表格接续和长文末段。 |
| W3 公共观察、0 图、长园所名 | 冻结 UI／原生另存为生成；Word 实际 1 页，整页检查未见裁切、多余空页或空图片占位。 |
| W4 室内观察、1 张竖图 | 冻结 UI 导出 v4；Word 实际 2 页，竖图方向／比例保持且完整在页，末页为非空分析续表。 |
| W5 户外观察、横竖 2 图、18 段长文 | 冻结 UI／原生另存为生成；Word 实际 3 页，已查看正文分页和末页两图；竖图在前、横图在后，比例保持，未见图文重叠或出页。 |
| W6 三图、18 段长文 | 普通 UI 加入第 3 图形成 v8，再从编辑页导出；Word 逐页及打印预览最终 4 页。三图在第 3 页、末表在第 4 页；初始状态栏曾显示 3 页，不能将该暂存值当最终页数。 |
| W7 混合三类、覆盖 5 图 | 普通 UI 将选集手调为户外 v11（5 图）→公共 v2（0 图）→室内 v4（1 图）。Word 逐页及打印预览 7 页，记录起始页 1／5／6 与手调顺序一致。6 个 drawing、5 个媒体文件（相同图片复用），图片关系顺序等于 W8 五图＋W4 单图。 |
| W8 本次编辑后导出 | 普通 UI 在当前五图稿新增独有观察目标标记，未另点保存，随后从编辑页导出；固定预览为成功保存后的 v11／5 图。Word 实际及打印预览 4 页，独有新标记、18 段正文和五图均存在，未交付旧稿。保存失败反例另见 §5.1，不改动本份教师样例。 |
| 恢复后的同类 Word | 冻结 UI 经原生取消→明确重试生成新文件；与恢复前 W5 整体 SHA 和每个 ZIP 成员字节一致。 |

八份均由本轮冻结 UI／原生另存为生成；逐页检查在实际 Microsoft Word 中完成，不以 XML 或旧样例替代。日计划模板中观察到楷体标题、仿宋正文，观察模板包含宋体；结构字体声明另存证据。未见漏图、方向错误、图片拉伸、图文重叠或额外空白页；正文核对另由 XML 和已保存快照支撑。W2／W7 起始页按实际逐页翻阅记录；Word 状态栏随光标／后台分页会滞后，存在差异时以实际渲染及打印预览核定，未执行打印。用户于 2026-11-01 明确确认 W1–W8 八份 Word 均通过，本轮指定 Word 教师体验收口。工程检查未单独评价教学内容质量，其他字体环境／DPI／WPS 未验。

真实占用／明确重试：先复制自有 W1 到独立 `occupied-test.docx`，Word 普通打开后实际文件锁阻止独占访问。冻结 UI 尝试保存到该副本，经原生覆盖确认后显示“保存失败：目标文件正被其他程序占用，无法保存；请关闭占用该文件的程序后重试”，没有误报成功。正常关闭该 Word 副本并选择不保存其临时版式状态；失败前后 SHA 完全不变。点击应用“重试导出”，再次原生选择同一路径并确认覆盖后成功；新字节与 W2 全部一致。原 W1／W2 八份验收文件另行保留，未拿被重试覆盖的副本替代 W1。证据 `word-matrix-check.json`。

### 5.1 冻结程序实际保存失败：保留当前稿并阻止旧稿导出

按用户追加要求，在首次页恢复 A 的独立合成根内，选择公共观察 v2、0 图。先正常导出 `SF-before-v2.docx`，完成原生保存后关闭预览、重开编辑页。记录全部 42 表逐字段基准、三个观察导出表的既有 ID／整行集合，以及合成根和外部导出目录的 Word 文件及 SHA。

独立 SQLite 连接以 `mode=rw` 打开本轮合成 DB，仅持有 `BEGIN IMMEDIATE` 写锁；不执行 UPDATE／DDL，不改权限或数据库配置。随后通过冻结程序普通界面，在原空观察目标中填写唯一 SF 标记。实际点击保存，约 5 秒后显示“本地数据库正忙，请稍后重试”；待保存结束、按钮恢复可用，再点击“导出 Word”。导出前再次保存失败，实际提示“导出前保存当前稿失败：请处理后再导出”。为捕获短暂提示，分别重复一次保存和导出；每次均等前一操作结束，没有自动重发。两类提示均由实际窗口截图观察，辅助功能树会滞后，未把树的旧 disabled 状态当最终结果。

失败结束后，编辑页仍保留完整新目标和原观察正文，版本仍为 v2，没有进入导出预览或原生另存为。写锁期间以及所有失败操作结束、释放锁后各以新只读连接核对：42 表逐字段不变；三个导出表仍各 3 行，既有 ID 和整行均未变；两个检查范围内的 Word 文件集合和 SHA 不变。故没有交付旧稿或留下新的持久导出快照、token、尝试记录。此处未抓取 HTTP 请求，不能把这些结果扩大为“完全没有调用任何导出 API”。

锁连接通过 `finally` 回滚并关闭，进程正常退出。之后明确点击保存，同一份保留稿成功成为 v3；只读 JSON 解码核对仅 observation_goal 改变，其余正文相等，integrity_check=ok、FK=0。首次探针误在转义 JSON 字符串中直接搜索中文，改为 JSON 解码后通过，该探针问题不记为应用缺陷。再从编辑页导出，固定预览明确为 v3，经原生另存为保存 `SF-after-v3.docx`（11,368 bytes，SHA `13831ef53d4aea44ebcb13d009519f0e4927648bb7cb9ec42b560ad3840aa90f`）；正文包含完整新目标。旧文件（11,271 bytes，SHA `3361e3b86116eb2c790d968fa4b303ff0aa89f4b636837e9003fce902a381145`）没有新目标且 SHA 未变。这两份为补充故障证据，未替换 W1–W8，也未另作 Word 全页版式验收。

随后正常关闭原应用，确认退出后启动同一 EXE 和合成根的新进程；打开公共观察，v3 及完整新目标仍在。重启验证首个启动被验证器设为隐藏窗口、没有可操作窗口；仅停止经路径和参数核准的该合成进程，改为可见方式重启后完成普通 UI 核对。这不是未保存稿的崩溃恢复测试，也未认定应用挂起。最终正常关闭测试应用。

本反例仅证明当前候选、本机合成档案、SQLite 写锁导致的明确保存失败路径；不覆盖断电、磁盘耗尽、进程崩溃或结果未知时关闭后的草稿恢复。证据：`SF-before.json`、`SF-ui-observations.json`、`SF-while-locked-check.json`、`SF-after-release-before-retry.json`、`SF-lock-held.json`／`SF-lock-released.json`、`SF-successful-save.json`、`SF-word-comparison.json`、`SF-restart-ui.json`。

## 6. 未验、证据与边界

本轮结论：目标预检、冻结包普通手工业务、完整备份／恢复与保护包再恢复、首次页直接恢复／坏包拒绝／空保护包、W1–W8 工程页检，以及 §5.1 数据库忙保存失败保稿／阻止旧稿导出，在本文所列本机合成范围内通过；用户另已确认八份 Word 均通过，指定 Word 教师体验收口。后端跨轮累计 848 项、桌面跨轮累计 491 项曾通过；桌面另有 1 个权限夹具受阻及 1 个既有跳过，完整首轮失败保持，不能称“所有测试单轮全通过”。产品／签名／发行没有整体验收通过。

用户明确本轮不进行跨 Windows 用户恢复测试：保持未验，不再安排本轮补测，不作为本轮交接阻塞；备份使用无 AI 凭据的合成档案，不能证明跨用户 DPAPI 失效／重填已实际验证。跨电脑、真实 AI、WebDAV、签名、更新替换和发行均未做。没有用原机 4551、旧包、旧 Word 样例或原五保护源的指纹代替本机证据。坏包和 §5.1 写锁保存失败另有本轮冻结 UI 实测；容量、并发和恢复崩溃反例按本轮源码测试范围，不能写成目标机真实断电、真实磁盘耗尽或全部 UI 分支已验。

私有证据别名：`kgm-win11-target-20261101-pydkf8u6`。包含环境／预检、逐文件核包、107 PE 签名、锁定安装日志、pytest 原始输出及 JUnit、前端输出、A／B／A2 逐字段和资源摘要、两份实际 UI 备份、三份保护包核对、八份实际 Word 及结构／恢复后字节比较、首屏坏包／直接恢复核对和 SF 补测。补测后另生成 `closeout-identity-check.json`／`test-status-closeout.json`：八份原 Word、三份保护包及交接 ZIP／PS1 的 SHA 均未变，默认业务／凭据根仍不存在；SF v3 新目标持久保留，integrity=ok、FK=0。补测前的 `final-identity-check.json` 和 `test-status.json` 保留为当时快照，不覆盖。原始路径、用户名、凭据和完整合成业务日志不进入公开提交。

原 OpenCode CLI 可读取版本和会话列表，但本机当前项目列表为空，原实施会话未在其中；本轮未新建实现会话、未调用模型生成改动。Codex 执行独立验证并整理文档，没有修改实现、测试、迁移或构建脚本。用户最后授权提交并推送本轮测试交接文档；只提交脱敏报告和入口修订，不改受测实现或原 main，不创建 tag 或 Release。

## 7. 测试入口与交接

普通目标机操作入口为 [便携测试手册](desktop-windows11-portable-manual.md)；本报告是目标 1 实际回执，手册中的空表仅作后续设备记录模板。候选 ZIP 和另带 PS1 必须先分别核对 §1 的原字节 SHA。PS1 的 d7cdb395… 指原交接制品，不能拿 Git LF／CRLF 检出副本静默代替。以后改脚本、重打包或修改受测源码须分配新身份，不延用本报告。

源码复验在精确受测提交的独立检出中执行，使用 CPython 3.14.7 x64、标准 GIL，环境放在 `desktop/.venv-d1`；依赖入口为 `desktop/requirements-d1.lock.txt` 和 `desktop/requirements-d1-build-constraints.txt`。安装须保持 `--require-hashes` 和固定构建约束，除已核定 proxy-tools sdist 外均用 wheel；pip 索引按用户要求使用 `https://mirrors.cernet.edu.cn/pypi/web/simple`，不重新求解或升级 lock。前端按 package-lock 执行 npm ci，验证和构建显式选稳定 Node 24.19.0。需要执行既有套件时，在检出根使用以下入口，并把日志／JUnit／临时根放到新的独立证据目录：

```powershell
# $targetPython 指向本检出的 desktop/.venv-d1/Scripts/python.exe。
# $targetEvidence 指向新建证据目录；$targetFrontend 指向本次成功构建的前端目录。
# 使用稳定 Node 在 frontend 目录执行 npm run test:d1、npm run typecheck、npm run build:d1。
$env:KGM_D1_FRONTEND_DIR = $targetFrontend
& $targetPython -X utf8 -m pytest desktop/tests -q --junitxml "$targetEvidence/desktop-tests.xml" --basetemp "$targetEvidence/desktop-work"
$env:PYTHONPATH = (Join-Path (Get-Location) 'backend')
& $targetPython -X utf8 -m pytest backend/tests/local -q --junitxml "$targetEvidence/backend-tests.xml" --basetemp "$targetEvidence/backend-work"
```

本轮前端输出目录为独立检出中的 `build/target-source-validation/frontend`，不是 fixture 默认目录；U2 验证必须显式传入成功构建的实际路径。保存首轮失败日志后，原失败 nodeid 定向复验与首轮分开记录，不将两轮相加改写为单轮通过。SQLite 写锁反例按 §5.1 在纯合成档案下独立执行；不把故障操作套用到教师原库。

教师确认交付目录别名 `2026-11-01-r03/teacher-word`，含下列原八份文件、`教师确认清单.md` 及 `word-files-sha256.json`。复制时逐文件 SHA 与冻结 UI 导出原件一致；教师后续人工修改副本不影响原始工程证据。用户于 2026-11-01 在本次会话逐名确认下列八份 Word“均通过”，八份教师确认状态均为**通过**；本轮指定 Word 教师体验收口。该回执不代替后续新包、其他环境或产品整体验收。

| 样例 | 文件 | 工程核定页数 | 教师确认（2026-11-01） |
| --- | --- | --- | --- |
| W1 | `W1-daily-single.docx` | 2 | 通过 |
| W2 | `W2-daily-merged.docx` | 6，起始页 1／3 | 通过 |
| W3 | `W3-public-zero.docx` | 1 | 通过 |
| W4 | `W4-indoor-one.docx` | 2 | 通过 |
| W5 | `W5-outdoor-two.docx` | 3 | 通过 |
| W6 | `W6-outdoor-three.docx` | 4 | 通过 |
| W7 | `W7-mixed-five.docx` | 7，起始页 1／5／6 | 通过 |
| W8 | `W8-current-edit.docx` | 4 | 通过 |

本机持久交接目录别名 `2026-11-01-r03`：`delivery-inputs` 保存原 ZIP／PS1，`private-evidence` 保存首轮日志、JUnit、备份／保护包和 Word 等原证据；新增补充证据与最终报告另存，避免覆盖保存失败补测前的快照。目录清单附大小和 SHA，绝对路径由私下交付消息提供，不写入公开仓库。受测源码 detached 检出、原合成根和主检出均保留；文档提交使用同一桌面分支的独立交接工作树，不把开发机后续源码放进本轮验证范围。
