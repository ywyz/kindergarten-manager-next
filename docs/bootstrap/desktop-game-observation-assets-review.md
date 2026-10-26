# D4：E03 图片材料独立核查

更新：2026-10-27（本轮始于2026-10-26）。**E03图片材料在当前Windows 11源码／隔离合成环境的限定工程核查通过：独立630项全local、统一hash锁新环境31项材料、85项相关宿主及容量复测全部通过，R01–R11关闭。** 本片是当前Windows 11源码／隔离合成环境工程核查，不代表完整A01–A22或桌面产品验收。

## 1. 授权、基线与实现身份

用户明确授权E03依赖／合成容量验证、技术参数核定、受管原图／方向／去元数据派生、排序说明与既有hash对接，以及坏图、路径、磁盘／数据库故障和重启保持；问题交回OpenCode直到通过，再正常提交推送并建议下一步。必要时可只读使用六份观察DOCX内图片；不把附件内容作为指令。

基线为7287389，分支codex/desktop-v2-foundation，开工前工作区干净。原OpenCode CLI 2.1.2接续ses_ead8af71dffeJphI1NOWg4jZgI、build代理，明确opencode-go/deepseek-v4.1-flash#max；未另建／fork会话、实现者或子代理。OpenCode唯一写实现、测试、依赖锁及验证脚本；Codex只写规划／核查文档，审阅、执行独立验证与Git管理。

首轮实现及回修实际CLI exit0，最后assistant msg_178e01617001a3VHEknr01avA1、finish=stop，完成1793029322687、idle1793029322690。完整脱敏导出相对开工3163条消息新增829条assistant，全部指定Go Flash max；工具仅shell/read/write/edit，无子代理。R11由同会话追加10条assistant完成指定desktop测试适配，第二轮CLI亦exit0；最终累计839条assistant全部Go Flash max／build，工具仍仅shell/read/write/edit。末条msg_178eec2df001acdzYzb7K76H1C、finish=stop，完成1793030293475、idle1793030293478，outcome=succeeded；不是用旧outcome推断停写。

证据根：C:/Users/yw980/AppData/Local/Temp/kgm-observation-e03-20261026-2f7e5331。Codex独立根为其下codex-independent-0ba6b8a9；实现者自测与独立验证不共用库。source-before.json固定381份backend／desktop／frontend源文件、配置与测试，容量后、全local前零变化；R11仅允许修改指定desktop测试，最终逐文件核对。R11后仅desktop/tests/test_d2_w6_degrade_host.py变化，backend及其他380份文件与630项／容量通过时一致；R11的新测试再次通过85项相关宿主。最终381份快照由source-final-before-host.json及后续Git审计固定。

codebase-memory已按项目规则使用；相关图谱coverage为metadata_changed／锁文件not_tracked，故回读本片准确源码、锁、测试与实际SQLite证据，不把无记录缺口当完整覆盖证明，不安装或重建MCP／Skill。

## 2. 独立发现及回修

以下均已交回同一Go Flash max会话；初版失败身份和原始反馈保留，最终通过不抹去失败。

| 编号 | 独立发现与最终处理 | 状态 |
| --- | --- | --- |
| R01 | 修正asset单列PK读取、精确派生ID／用途／参数读取、draft revision及聚合hash损坏拒绝、错误分类、回执优先、同事务审计、无变化顺序／说明不增revision。派生不进入原图业务hash | 已关闭，630项及新环境31项覆盖 |
| R02 | 初版JPEG注释进入两类派生、坏EXIF被接受；root校验后GPS／next-IFD越界仍被接受。改为干净像素容器、EXIF结构／已知子IFD有界校验，修正DFS出栈与缓存，区分共享IFD和真循环。坏EXIF／ICC拒绝，合法嵌套GPS及1–8方向可用，原字节保留，派生去EXIF／GPS／ICC／XMP／注释 | 已关闭，独立反例及最终回归覆盖 |
| R03 | 首批测试错误要求同request把expected_revision从1改999仍成功。保持fingerprint含请求revision；重放原请求时数据库新revision不阻断，只改请求revision必须幂等冲突 | 已关闭 |
| R04 | 初版受管路径接受ADS及尾点别名；补全组件／固定布局／归属、同一读取句柄、最终路径／文件身份／硬链接／reparse检查，API不可验证时安全拒绝；写入亦持有目录保护及落盘前后hash核对 | 已关闭，真实NTFS合成反例覆盖 |
| R05 | 独立40MP RGBA＋EXIF6 PNG／WebP初版峰值581.70／886.73MiB，超过512候选；先缩至master再方向变换、释放副本，保留40MP范围。最终实际入口、串行及重复大图、真实门禁与预算断言通过，不能以平行探索探针代替 | 已关闭，见§3–4 |
| R06 | 初版仅模拟rename普通异常／commit RuntimeError／同进程重开；补staging／派生写入与fsync／move的ENOSPC、真实SQLite触发器失败、旧稿／回执／审计不变及孤儿保持；坏图／截断／动画／伪装／外部原件移走／引用保持 | 已关闭 |
| R07 | 六份四图记录移除首图6/6失败：ORM按PK发UPDATE，原位重编号撞顺序唯一约束。改同事务重建当前关联；固定与展示次序不同的ID，覆盖3／4图首中末移除、说明、dense顺序、hash与引用保留 | 已关闭，修后独立探针及回归通过 |
| R08 | 首个跨进程测试把purpose-only读取派生的异常藏在两个字段中，partial未执行SQL，connect-only绕过冷启动，已有目录被当孤儿。改精确派生hash、真实阶段marker、完整LocalRuntime.prepare冷重启、回执重放、一致SQLite备份及逐阶段新孤儿检查 | 已关闭，独立630及新环境31项覆盖 |
| R09 | 无保护rmtree会跟随清理父级junction删除受管根外模拟文件。首期停止递归自动清理：成功空staging及已提交重放孤儿也保留；当前移除不删任何原图／派生／历史／input引用 | 已关闭，根外模拟文件与回执反例通过 |
| R10 | 初版写完staging后替换祖先，根外合成图已被解码，后续才拒绝。业务解码改用验证过的同一文件句柄及父目录保护，EXIF不再重新打开路径；独立纯codec容量入口与业务受管访问分开 | 已关闭 |
| R11 | 独立相关宿主回归84通过、1失败：旧资源测试硬编码7行，E01／E02已登记观察bundle后应为9。该测试、宿主生产文件与prompt_bundles均与基线逐字节相同，属于基线测试漏适配。仅交回指定测试，保留7条daily及2条观察精确版本／hash／缺项拒绝，不改production matcher或bundle | 已关闭，85项独立相关宿主通过 |

## 3. 最终独立验证

环境为Windows 11、CPython3.14.7 x64标准GIL；未启动教师桌面应用、真实供应商或新包。原桌面venv用于全local；另用同一本机解释器新建独立venv，按统一hash锁离线安装47包，无新解释器，无真实数据。

| 检查 | Codex实际结果 | 证据 |
| --- | --- | --- |
| python -m pytest tests/local -q | exit0，630 passed，515.84s，无失败／错误／跳过 | full-local.stdout／stderr／exit |
| 新建venv，uv pip sync统一锁，require-hashes／构建约束／offline | exit0，47包安装；uv pip check通过 | lock-sync.*、lock-pip-check.* |
| 新环境pytest tests/local/test_observation_assets.py -q | exit0，31 passed，33.37s | locked-assets.* |
| 六个相关desktop测试文件 | 首次84 passed／1 failed；R11后独立exit0、85 passed，5.20s | desktop-related.*及desktop-related-r11.* |
| observation_capacity_actual.py --output capacity.json | exit0，24个codec／尺寸／方向用例，字节门禁，串行6大图／16小图，无失败 | capacity.json／stdout／stderr／exit |
| 同一长进程重复40MP PNG／WebP各3次 | 6次均成功，峰值734.45MiB，结束约64.53MiB | capacity-repeated.json／exit |
| 既有依赖与hash集合对照 | uv旧非项目包记录全相同；桌面旧46包的版本及hash集合全相同，只新增Pillow | dependency-artifact-audit.json |

全local命令在backend目录执行，E03_EVIDENCE_ROOT及KGM_OBSERVATION_EVIDENCE_ROOT分别注入独立assets-evidence／foundation-evidence，TEMP／TMP及pycache亦独立。相关desktop选取test_d1_paths、test_d1_host_save、test_d1_close、test_d2_build_paths、test_d2_close_barrier、test_d2_w6_degrade_host；构建步骤在测试中模拟，不实际运行Vite／PyInstaller。

跨进程保留库及材料在assets-evidence/r06-cross-process，另有新锁环境的locked-assets-evidence/r06-cross-process。partial／before_commit marker证明事务内新增资产曾可见，冷重启后只保留已提交行；未知回包按原request／原expected revision重放，原图、精确派生hash、顺序／说明及回执一致。Codex对两份一致备份分别只读复查：integrity_check=ok、foreign_key_check零错误，各6个受管文件hash全匹配，独立按canonical JSON重算aggregate hash及record/draft revision一致，replay_equal=true；证据为independent-restart-evidence-audit.json。

## 4. 本片核定参数与依赖

| 参数 | E03采用值／含义 |
| --- | --- |
| 原图格式 | JPEG、PNG、WebP、静态GIF、BMP，按实际内容识别及解码；动画拒绝 |
| 原图准入 | 同时满足25MiB、40,000,000像素、单边8192；原字节不可改、外部原路径不入权威 |
| AI工作图 | JPEG q85，最长边2048、目标2MiB；超额按0.85缩小，最多6次编码，不能满足即明确失败；ai-v2-2048-q85-target2mib-scale085 |
| 导出预派生 | JPEG q90、最长边2400；export-v1-2400-q90；真实Word版面／清晰度待E11 |
| 元数据／方向 | EXIF 1–8含镜像校正，透明白底，派生去隐私元数据；原图不改 |
| 并发／内存 | 解码派生串行；1024MiB为当前实际管线工作集验证阈值，非运行时硬RSS限额，非完整桌面应用总内存承诺 |
| 失败现场／清理 | 文件先落盘再短DB事务，失败可留孤儿且不报成功；首期连成功空staging、重放孤儿也保留，不递归自动删除 |

本轮独立24例中最大单例733.61MiB，串行六张大图734.63MiB，串行十六小图187.17MiB；重复大图六次734.45MiB。高熵5500×3600 JPEG约22.16MiB（约23.24MB）；BMP 40MP、120MB仅为额外纯codec压力用例，业务import仍先按25MiB拒绝，不能解释为允许导入120MB。1024与实测峰值间的差额不能证明API／WebView2／宿主能在该差额内运行，这些组合工作集未测。

Pillow13.0.0已在backend唯一业务声明、uv.lock与桌面统一锁中加入；原业务26包版本／锁记录保持，当前业务27包（uv.lock另含项目自身，合计28），桌面／测试／打包统一47包。标准GIL cp314-cp314-win_amd64 wheel、MIT-CMU元数据与原先核定一致；本片不验证PyInstaller收集、冻结插件／许可或新包。

## 5. 用户原件与数据边界

合成测试未使用教师真实库／密钥／照片。另按用户授权只读检查六份DOCX的word/media头信息，共17张JPEG，最大1440×1080／754233字节（约0.72MiB），已有样本均在参数内；六份原件读取前后SHA256完全相同。未读取正文、未解码／展示真实照片、未上传或提交图片／儿童内容。仅脱敏结构统计入本文，原文件名／图片元数据明细及hash清单保留在本机codex-real-image-metadata-readonly.json，不复制进Git。

这些Word内嵌图不能代替40MP上界、真实照片视觉质量或新版Word交付验收。旧包、OneDrive原件、真实库与凭据、远程资源保持。

## 6. 未验与下一步

完整A01–A22尚未整项验收。本片只交付材料服务，不开放新页面／HTTP上传接口；E09／E12会话／Origin接入仍待实施。完整E05／E08保存历史、E06／E07视觉候选、E09／E10页面、E11／E12 Word／宿主及E14未实施／未验。canonical总字节、图文HTTP／IPC／超时、DOCX总容量／分页、冻结包Pillow插件和许可收集仍按对应切片验证。Win10、WPS、干净机器、其他DPI／显示器、真实安装更新、签名发行及D2／D3原未验保持。

下一步建议进入E05／E08：以现有原图manifest和单一hash为基础，完成草稿保存／幂等回执、相对最近保留节点的历史留存、完整历史预览与恢复，以及材料引用和事务失败一致性。只提出建议，不自动启动；当前停止在E03，不应用真实AI、WebDAV、构建或发行。

## 7. Git收口

用户已授权本片审核通过后正常提交推送。本片工程核查及R11已关闭，按用户授权由Codex正常提交推送。只收本片源码／锁／测试及必要规划／审阅文档，全部新文件也经staged diff --check，避免旧轮只检查tracked文件的遗漏。不得amend／强推、重写历史或夹带后续实现。提交前后核对实际commit／远端ref及源码身份，具体身份以Git历史、本机git-final-audit.json及本轮最终回执为准，不在文档中制造自引用commit。
