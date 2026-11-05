# 当前：两项限定核验通过，接续同提交制品与目标增量

更新：2026-11-05。唯一执行入口，继续`codex/desktop-v2-foundation`。本轮从干净0e51491普通fetch／快进接收`173880de7ac67b8fd847d13281f913f4d282fab3`，tree `674c7ed19735fdde97eef979decb97472c60ce2f`；没有新merge／rebase／force。用户明确授权的两项最小修复、验证和审核后普通提交推送已实施，结果见[开发机限定核查§8](../bootstrap/desktop-regression-repair-review.md#8-2026-11-05来源门与受管恢复验证器回修)。本文件不循环回填自身SHA；准确新交付以实际分支、父提交、tree及远端回执为准。

[原测试机§7](../bootstrap/desktop-windows11-white-concurrency-review.md#7-2026-11-050e51491原测试机增量)保留0e51491新完整local1229通过、桌面627通过／1缺旧包skip、源码恢复私下副本及CI旧来源缺口的各自身份。原中断完整轮的1个失败标记无详细堆栈／退出，顺序映射不等于原因；继续保留，不宣称本次已定位或修复。已确认[手动重开规格](../specs/desktop-renderer-recovery.md)保持，不重复询问产品决定。

## 1. 本轮完成与独立结果

- **来源门**：`renderer_recovery.py`、`renderer_recovery_native.py`纳入构建前后product freeze、required freeze、必要归档模块及production分类；受管源码验证器和新测试纳入verification来源。实际范围289文件；验证器没有强制打进产品PYZ。缺来源／缺freeze／改hash／前后变化／真实CArchive-PYZ漏模块或改代码的反例均触发拒绝。
- **受管验证器**：两处活动host观测改为锁内读当前已绑定状态，产品bootstrap语义不变。真旧票据拒绝且前后状态不变；新service port旧token401／新token200；仅自有Core故障、完整业务／资源指纹、正常关闭和独立进程冷启动保持。补persist／输出边界，删除初稿多出的等待；无新增sleep／预算／重试／skip。
- **Codex实际复验**：相关四文件119通过；最终验证器6通过，均无失败／错误／跳过。受管Page.crash和Browser.crash各独立新合成根exit0，49表／12资源、task／execution／attempt各4→4、完整fixture及独立冷启动指纹一致，正常关闭／close_latest通过。三个真CLI边界反例exit2且不创建错误根；篡改expected完整指纹而计数仍同的负对照exit1。最终550非Markdown文件前后SHA相同。
- 原生A／B和Command Go实际request metadata均为指定Flash V4.1 max，无fork／子代理／换模；A写来源门四文件，B写验证器两文件，C只读交叉审阅，均已自然停写。旧责任／Git白名单关闭，不重放或跨机冒充session。
- 现有3.14.10 x64标准GIL及锁定依赖；新短TEMP及其内basetemp、禁dotenv／pyc、SQLAlchemy纯Python和Python网络守卫。前端源码未变，三份已核同源产物SHA复核后复用，没有无故重复完整backend、旧Word／IME。主／子进程守卫加载；更新检查的非loopback解析被拒不等于OS／WebView全局隔离。应用付费AI请求0。

## 2. Git与自动CI收口

Codex审核准确六份源码／测试及对应正式文档的原字节和Git规范化blob、单parent173880de7ac67b8fd847d13281f913f4d282fab3及index tree，才交原开发机OpenCode A普通提交／推送，并独立核提交tree、远端和工作树。用户本次已明确授权，无需重问是否提交。不能add-all／amend／rebase／force，不能改main／默认分支／可见性、tag或Release；同步若不能快进，停止报告，不沿用旧merge授权。

push若自动产生新CI制品，只读核本次完整提交的可信成功run／attempt、原外ZIP／内ZIP和PS1、package-info.source_commit、build_id／revision及修复后来源门。对两个生产恢复模块既核真实归档代码同源，又核289文件freeze范围；verification来源不强行变为产品模块。CI检出换行与本机原字节分开核，不用本机digest冒充CI，不制造构建前freeze时间。不自动dispatch／重跑；未取得新制品就只记录源码结果。具体自动CI结果和字节身份以本提交对应run及最终只读回执为准，不预先宣称静态或冻结运行通过。

Windows2022构建／静态结果不是Windows11冻结运行。旧run41855931829／attempt1是0e51491且漏新恢复模块来源，不能替代本轮新包。

## 3. 下一步：按新身份做冻结恢复限定增量

两项源码核验已通过。随后应在原Windows11测试机按新包身份安排恢复增量；先核当前目录、分支、HEAD／远端及本地差异，保留他方资料，只fetch／快进，再核新来源门和自有Core受控触发能力。开发机SAC4551不执行受阻冻结EXE／helper，不换名／换路径／去来源标记／降保护重试。不能以本机两个源码窗口、旧私下副本或旧包替代新冻结包结论，不添加产品调试开关。

受影响完整local已经在测试机0e51491下新根1229通过；本轮不改生产执行器／worker／迁移／预算，禁止同源无新相关变化时再盲目完整重跑。若同类失败复发，保留精确节点、stdout／JUnit、spawn／ready／permit／SEND／落盘及子进程实际退出，先定位最小前序影响，不以sleep／扩大预算／重试／skip或串行化并发采用消除失败。

原AI体验档案及凭据根按[配置保留§6.7](../bootstrap/desktop-windows11-white-concurrency-review.md#67-后续拉取代码时保留本机ai配置)原地保留；同机同Windows用户普通启动显式`--data`／`--credential-root`，不新建空档案索key，不复制DPAPI。仅核配置保留无需额外付费请求，不自动重发unknown。故障／自动验证另用新合成根，不触已配置原档案。

## 4. 持续边界

原档案／照片／配置／凭据、旧包／Word／备份及首失败现场保留；只提交脱敏文档和受管来源／测试，不提交私下副本、日志／XML／图片／数据库、下载字节或证据索引。所有写根先核绝对路径、reparse与源／目标／旧根边界，不删未知文件、不全局kill。

不安装升级依赖／工具／Skill／MCP，不额外应用真AI、签名、安装更新、WebDAV、远控或发行。原自然白屏精确触发、Word/r历史差异、冻结恢复运行、Windows symlink特权、Win10／WPS／其它显示条件／跨用户／长根206等未验保持；不重验旧39项、13份43页Word、微软拼音或W6跨120秒睡眠，不/r／regserver／Office修复，不把限定工程通过等同产品整体验收。
