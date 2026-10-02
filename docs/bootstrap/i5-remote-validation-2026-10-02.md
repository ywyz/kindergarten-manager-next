# I5 最小修复、远程部署与验收交接（2026-10-02）

状态：**范围竞态已修复并提交；远程独立验收实例已部署，自动检查与公网 HTTPS/API 检查通过；Trae Work 浏览器落盘和 Office／WPS 逐页验收未执行。** 不宣布 I5 片4完成。

## 授权与基线

用户本轮授权先修复遗留问题，随后 commit/push；要求 SSH 密钥连接 `root@bwh.ywyz.tech` 部署，替代本机 WSL 验收服务器，浏览器由 Trae Work 验证。Windows 10／11／Server 2022／Server 2025 与 Office 2010 以上桌面 Word／WPS 文字任一组合完成必需案例即可通过，权威口径见 [当前验收环境](../specs/i5-validation-environment.md)。

开始 HEAD 为 `0e473b2e4205cb6bec0e9f8ba07ccdf3f3307406`，分支 main；已有两份未跟踪协调者文档 `review-and-browser-check-2026-10-02.md`、`i5-followup-opencode-prompt-2026-10-02.md` 已保留并标注新指令替代关系。用户明确答复“本轮允许你直接最小修复”，仅对两处导出竞态例外，后续默认业务由 OpenCode 写入不变。

修复提交：`2cb8d81556f47936e236dadedcb37bf3cec5b3c8`。本机 Git 身份缺失，提交命令沿用仓库最近提交的 `ywyz <admin@ywyz.tech>`，未修改全局 Git 配置。部署归档由该提交生成，文档收口提交单独完成，不含运行时凭据。

## 修复与行为证据

- `DailyPlanView.vue`：日期范围或模式变化时同步递增既有请求序号、释放旧 loading，并清除 ack、facts、expected_context、reason 和旧错误。
- `WeeklyPlanListView.vue`：新增范围 watcher，同步使旧请求失效并清除旧错误；既有 seq/finally 判断保证旧请求不清除 B 的 loading。
- 使用同步 watcher 避免选择已改变但失效处理尚未执行的窗口；保留双击防重、关闭、切班与卸载机制。未改后端服务、schema、迁移、模板、业务需求或依赖锁文件。
- `frontend/scripts/check-export-range-race.mjs` 用既有 Vue／TypeScript 编译实际 SFC setup，使用真实 Vue watcher 和可控制完成顺序的 API Promise，覆盖两视图旧200／旧409／旧错误，在有／无B请求时忽略旧结果、日模式切换、缺项确认清理和双击：**18项通过**。同脚本在修复提交前读取 HEAD `0e473b2` 执行 `--baseline`，第一项失败于改选择后 loading 仍为 true。此证据属于行为检查，不代表真实浏览器下载。

旧H表案例编号、日期跨度与份数超限、资源不同轮次歧义已补充澄清；下一轮统一R01–R16。教师显式发送class_id属schema无效字段422；跨班403用周计划单份请求验证，不能将参数校验错误当成权限案例。

## 环境与自动检查

| 项目 | 本轮实测 |
| --- | --- |
| Windows | Microsoft Windows Server 2025 Datacenter，10.0.26100，build 26100，64位；CIM只读采集 |
| PowerShell | 7.6.6，`D:\Program Files\PowerShell\7\pwsh.exe`，本轮可直接调用 |
| 本地代码运行时 | Node 24.19.0、npm 11.19.1、Python 3.14.7；npm与uv官方临时工具已校验integrity／SHA-256，不全局安装 |
| 远程系统 | Ubuntu 24.04.5 LTS x86-64；服务器自报主机名cloud.ywyz.tech，SSH目标仍是用户指定bwh.ywyz.tech |
| 远程Python／uv | 系统Python 3.12.3、目录内uv 0.12.21；显式选择既有解释器，未下载Python |
| MySQL | 已存在mysql:8.4.11镜像创建新容器，运行版本8.4.11／InnoDB；未复用旧业务库 |
| 迁移 | 既有Alembic链应用至`20260924_i4_weekly_plans`；未新增revision |

Windows后端首次`--locked`安装受用户级包源配置影响而停止；显式`--no-config --default-index https://pypi.org/simple`后按原`uv.lock`成功。前端按原`package-lock.json`执行npm ci。两个锁文件内容未变。

| 检查 | 本轮结果 |
| --- | --- |
| 延迟响应行为 | 18通过，修复前基线有失败证据 |
| 前端typecheck | 通过 |
| 前端build | 通过；主JS 1135.45 kB、gzip354.11 kB，保留既有非阻断体积告警 |
| Windows后端全量单测 | 533通过，17.233秒 |
| 服务器后端全量单测 | 533通过，12.453秒 |
| 服务器I5 MySQL集成 | 30通过，32.947秒，0skip；guard核对127.0.0.1:13386、白名单测试库、8.4.11／InnoDB／head |
| 公网HTTPS/API | 20项检查通过，10份API文件完成ZIP完整性、内容断言与SHA-256；[脱敏摘要](i5-public-http-checks-2026-10-02.json) |

公网检查从Windows经有效TLS连接真实服务器，验证五角色登录、Secure／HttpOnly／SameSite=Lax Cookie和no-store、空内容409及context确认、普通／长过程／三份合并、31/32与8/9实际份数、当前V2与历史V1而不混入V3、未确认／无匹配404、同班导出、跨班／待分配403、管理员显式班级与缺失422、缺Origin403。实际中文Content-Disposition在API层已核对，浏览器落盘中文文件名仍待实测。

第一轮检查在错误地预期“教师显式class_id为403”时停止，此前9次成功导出；修正测试预期并使用跨班周单份403后，完成轮10次成功导出。数据库实际19条`export_word`与两轮成功请求数一致，失败路径未多出成功记录。日内容仍32版本、周草稿21版本／确认10版本，与播种数量一致，导出没有追加计划内容；[数据库摘要](i5-remote-db-summary-2026-10-02.json)含低权限应用账号仅本验收库CRUD授权。更强的事务／失败零业务写入证据由30项集成断言提供，不以行数检查冒充完整字段对比。

## 实际部署与资源去留

| 资源 | 身份／状态 |
| --- | --- |
| HTTPS入口 | [kg-next-verify.ywyz.tech](https://kg-next-verify.ywyz.tech)，Windows访问首页200与`/health`正常；入口为已构建资产，不是Vite开发服务器 |
| 目录 | `/opt/kindergarten-manager-next-i5/`；`current`指向`releases/2cb8d81556f47936e236dadedcb37bf3cec5b3c8` |
| API | `kg-next-i5-api.service`，active且enabled，独立kg-next-i5系统账号，单uvicorn进程，仅127.0.0.1:18090 |
| DB容器／volume | `kg-next-i5-mysql-20261002`／`kg-next-i5-data-20261002`，仅127.0.0.1:13386，restart unless-stopped，保留 |
| 验收业务库 | `kg_next_i5_acceptance`；应用账号`kg_next_i5_app`仅该库SELECT／INSERT／UPDATE／DELETE，无DDL全局权限 |
| 自动测试库 | `kindergarten_test_i5_fresh`，独立测试账号；I5破坏性guard不能指向验收业务库，测试不在其上执行 |
| 服务配置／凭据 | `/etc/kindergarten-manager-next-i5/`，root目录0700、文件0600；无明文凭据入Git或日志 |
| Caddy | 新snippet`/etc/caddy/kg-next-i5/verify.caddy`；主配置只增加该目录import，先校验候选再reload，旧配置备份到`evidence/Caddyfile.before-i5` |
| TLS | Let's Encrypt YE2，CN为新子域名；有效期2026-10-02 14:18:41至2026-12-31 14:18:40（UTC+8），标准客户端证书校验通过 |
| 原应用 | 原有容器继续运行；原staging-manager HTTPS仍307，与部署前观察一致；未读取旧表或改旧业务代码 |
| 资源观察 | 收口时可用内存约491 MiB、swap使用250 MiB、根盘可用6.1 GiB；API／新DB各384 MiB限额，不代表容量验收 |

源码tar SHA-256 `6867bdb67c4a272affd8947473bdf195685eb7899a1666940c7fd0e019b5336f`；前端dist归档 `7d8fc2a94c5df5e2168dd2bc0d988d4ec4e88c855e680af08b24829ce7118825`，本地与服务器一致。固定模板哈希前后及服务器均一致：日`99008f92…`、周`24ccaa9e…`（完整值在10月1日记录与规格中）。

部署工具与日志保留在该实例tools／incoming／evidence中；本机工具与API检查文件在仓库外`C:\Users\admin\.codex\visualizations\2026\10\02\01a0fb52-d101-73a2-85c8-f71c56b27c23\i5-work`。实例与夹具保留供Trae Work验收，不按旧记录清理。若需停用，先停止并disable准确的`kg-next-i5-api`，移除新Caddy snippet并验证reload；DB／volume／凭据保留待用户决定，不执行全局容器清理或删除旧应用。

## Trae Work交接与未执行项

[完整提示词](i5-trae-work-prompt-2026-10-02.md)已完成，包含远程入口、私密账号领取、[精确夹具ID及日期](i5-remote-fixtures-2026-10-02.json)、R01–R16、数据修改顺序、份数判定、下载与逐页证据、审计及退出条件。

初始合成账号5个、班级2个、12周日历84天、32份日计划；09-02全空、09-03长过程带模拟拆分基准；第6周六天、第7周七天、第8周停课及周日调休。9份周确认，第2周V1／V2已确认、V3草稿，第10周未确认。公开测试builder的固定令牌未进入可用会话，管理员领取已锁定；口令随机生成，私密文件root-only，本机交接文件限制admin／SYSTEM读取。

**未执行**：Trae Work浏览器操作与真实下载落盘、Office／WPS实际打开及全部页面、桌面字体与打印预览。当前Windows Server 2025符合可选系统范围，但不因此认定桌面软件已验证。W2纯移动／纯删除／仅格式子例、W6非空模拟材料及改选来源仍须对应夹具与实际执行；初始模拟基准不代表AI运行，空材料不能冒充非空材料映射通过。已有提示词对缺夹具或工具能力给出受阻交接要求。

真实AI、个人提示词、数据库持久任务仍未实现；约30人容量、S3备份恢复、正式生产上线不属于本轮通过结论。I5片4待Trae Work与桌面证据收口后再判定，不能用本轮自动测试或HTTPS200替代。
