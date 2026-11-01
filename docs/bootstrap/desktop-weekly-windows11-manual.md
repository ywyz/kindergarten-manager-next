# 周计划 Windows 11 验证包：下载与另一台电脑测试

更新：2026-11-02。适用本轮包含周计划 Q1–Q4、明暗模式和完整备份恢复的**新身份未签名内部测试包**。本轮构建与静态结果见[核查](desktop-weekly-windows11-review.md)，[当前入口](../tasks/current.md)控制执行范围。旧 r03 目标1及 W1–W8 教师确认保持[原身份](desktop-windows11-target-review.md)，不能填作本包通过。

## 1. 从 GitHub 下载

打开仓库的 [Actions](https://github.com/ywyz/kindergarten-manager-next/actions)，选择 **Windows 11 weekly validation build** 工作流中本轮桌面分支、指定提交且成功的运行，进入页面底部 **Artifacts**，下载验证包。需登录有仓库读取权限的 GitHub 账号；参见[GitHub下载说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)。实际运行链接／提交／制品名以本轮核查记录为准。

GitHub 下载的是一层制品 ZIP；先解开这层，取得里面的**程序 ZIP**、预检 PS1、身份／校验文件和本手册。随后核验并解开程序 ZIP。程序需完整保留 `KGNext-E14` 目录及其 `_internal`、资源和许可证，不能只复制 EXE。

GitHub 构建与本机构建各有自己的 build_id、freeze、ZIP SHA，不混用。逻辑程序文件名仍为 `KGNext-E14-win11-r01.zip`，不凭文件名判断轮次。将成功运行摘要中的 ZIP SHA、build_id、PS1 SHA及数据库版本抄到下面命令；不能仅信同一下载目录里可一起被替换的校验文件。

工作流在 GitHub 的 Windows x64 runner **构建并静态检查**；它不证明另一台 Windows 11 的策略放行、普通运行、Word或教师体验。无须在目标机安装 Python、Node或开发环境；需核对实际 Windows 11 x64、WebView2 Runtime及安全策略。ARM64等条件先记未适用，不改兼容层冒充通过。

## 2. 核包与只读预检

普通权限 PowerShell中执行。只改开头五项为实际文件位置和**该次成功运行摘要**的值；使用新的自有短目录，数据／凭据子目录此前均不存在。不要把报告、原始ZIP或脚本放进程序解压目录。

```powershell
$zip = (Resolve-Path -LiteralPath '<程序 ZIP 完整路径>').Path
$check = (Resolve-Path -LiteralPath '<check_windows11_target.ps1 完整路径>').Path
$expectedSha = '<运行摘要 ZIP SHA-256>'
$buildId = '<同一运行的 build_id>'
$expectedCheckSha = '<同一运行的 PS1 SHA-256>'
$revision = '20261101_0007_local_weekly'
if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedSha) { throw '程序 ZIP 身份不符，停止。' }
if ((Get-FileHash -LiteralPath $check -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedCheckSha) { throw '预检脚本身份不符，停止。' }
$trial = Join-Path $env:TEMP ('KgmWeekly-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
if (Test-Path -LiteralPath $trial) { throw '测试根已存在，停止。' }
New-Item -ItemType Directory -Path $trial -ErrorAction Stop | Out-Null
$extract = Join-Path $trial 'candidate'
$data = Join-Path $trial 'data'
$credentials = Join-Path $trial 'credentials'
Expand-Archive -LiteralPath $zip -DestinationPath $extract
& $check -ExtractRoot $extract -ArchivePath $zip `
  -ExpectedArchiveSha256 $expectedSha -ExpectedBuildId $buildId `
  -ExpectedDatabaseRevision $revision -DataRoot $data `
  -CredentialRoot $credentials -ReportPath (Join-Path $trial 'preflight.json')
$LASTEXITCODE
```

脚本核对系统／原生架构／WebView2、可读策略、实际文件集和身份、PE签名，以及输出隔离；不启动应用。退出0表示该台电脑只读检查通过，1为失败，2为不完整／未知；均不单独证明实际启动获准。报告的 `self_current_machine_only`仅指运行脚本的这台电脑。保留 `$trial`供下面继续使用。

若脚本被执行策略拦截或预检有失败／未知，保留错误并停止相关步骤；不使用 Bypass、解除来源标记、改名、粘贴整段脚本、管理员重试或关闭保护。可在 Windows设置只读记录系统类型、WebView2 Runtime和 Smart App Control状态，读不到的策略记未知。主EXE若受安全策略阻止，记录错误码、签名状态及首失败后停止，不换路径重试。当前4551开发机不执行本候选或helper。

预检脚本 SHA绑定交接副本完整字节。Git检出可能改变行尾；不改预期SHA或重写行尾来凑通过，应取该运行交付的原字节文件。默认真实档案仅查是否存在，不打开其数据库／凭据／旧备份。

## 3. 普通入口与周计划

预检适用且相关结果明确后，用同一新根启动普通入口，不加selftest、不直接改库：

```powershell
$exe = Join-Path $extract 'KGNext-E14\KGNext-E14.exe'
& $exe --data $data --credential-root $credentials
```

1. 建立合成教师、园所、班级和学期；不填真实AI密钥。确认周计划入口、日计划／观察入口及明暗切换可用；正常关闭后用相同两根新进程重开，设置保留。
2. 为有教学日的一周保存本人日计划，周计划读取**本人**来源；搭班两类信息手填。补主题及手工内容，分别试人工覆盖和明确留空；明确刷新来源后，这些人工决定仍保留。检查保育员／名单可空的真实缺项提示，不能擅自阻止已允许的保存／确认。
3. 检查保存、明确确认、历史三个动作和版本显示。改变园所／班级等设置后，既有周的创建表头不应漂移。切周／切学期／离开／正常关窗后重开核对自动保存结果；保存不能自动确认。遇失败／冲突／结果不明先保留输入和现场，不猜成功。
4. 保存并确认一版A；随后保存新版B，再输入尚未保存的主题标记。明确选择**旧确认A**导出，核文件来自A，当前编辑仍在，不能因导出隐式保存／清稿。之后正常关闭所触发的自动保存单独记录，不倒算为导出行为。
5. 另测日计划保存／历史／Word，以及三类观察的选图、排序、说明、保存、历史与重开。用自有合成横／竖图，保留原图独立性；无真实AI也应完成手工业务。第二实例报档案占用时记录，不强开、不删锁或全局kill。

原生文件操作分别记录取消、成功、测试文件被 Word占用导致失败，以及解除占用后的**明确重试**。取消／失败保留正文、照片和正确结果提示；若占用未触发失败就记该分支未覆盖。未知结果先核文件，不自动重复请求；不同导出功能按各自覆盖确认契约执行。

## 4. 新周 Word 与教师确认

每份从**本次候选真实UI／原生另存为**生成，记录build_id、来源确认版本、文件别名和页数。用实际 Microsoft Word逐页核标题／创建表头／日期、全部内容、续页、表格边框、字体及最后一页；不以XML、旧样本或源码窗口代替。没有Word则页检保持未验；教师本人确认单列。

| 样例 | 应核对的内容 |
| --- | --- |
| WW1 五日周 | 本人来源、搭班手填、主题与四栏、创建表头、教学日与非教学日格。 |
| WW2 六／七列 | 合成日历确有周末教学日时的真实列数；不得为凑列数改业务库。 |
| WW3 跨月／长文 | 完整周日期范围、长园名、四栏长文BEGIN／END与续页，无裁切／重叠／漏尾。 |
| WW4 零教学日单份 | 经正常设置调整、明确刷新并确认形成零教学日版本，再单份导出该指定版本；核真实创建交集日期与五列空教学格。 |
| WW5 旧确认／原生另存为 | 原有教学日旧确认A仍保留A原教学内容，不混入B或未保存标记；取消／占用失败／明确重试分别核旧文件保持、重试来源正确及当前编辑保留。 |

日计划单／多日及观察三类型／混合、0／1／2／3／5图、横竖／长文／手调顺序作相关回归。旧r03指定W1–W8教师通过不迁移给本次新文件，也不要求重测微软拼音或跨120秒睡眠。

## 5. 完整备份、恢复与保护包

1. 在合成根保存“工作A”：日计划、三类观察及合成照片、周草稿／确认历史／表头，以及亮色偏好。通过正常UI分别创建明文与合成密码加密 `.kgmbackup`，输出到 `$trial` 下独立 `backups`目录，位于数据／凭据根外。
2. 改为可辨认的“工作B”，保存新周主题／版本并切暗色。正常UI选择A备份，完整校验／预览后明确替换；先试取消，取消不替换。用另存副本测试坏包；加密包另验错口令、取消和正确口令，不破坏唯一原包。
3. 恢复A后核周草稿／确认历史／日来源、创建表头、日计划／观察／照片顺序及亮色；保留界面给出的完整恢复前保护包。
4. 在恢复的新窗口编辑并保存，正常退出后新进程重开核内容；再通过正常UI预览并恢复保护包，找回B、暗色和B的历史／照片。每次产生的保护包都保留，不自动清理。
5. 另一个新数据／凭据根验证首次页直接恢复及空业务保护包；失败／取消／恢复未明确完成时，核档案仍可用并保留首现场。

只使用本轮新包自行生成的合成包。外部Word和原图另行保管；不搬DPAPI、凭据根或可携带主密钥，不将旧源码合成备份说成本候选生成。跨Windows用户凭据恢复仍未验；本次普通另一台电脑测试不自动扩大该范围。不调用真实供应商、WebDAV或安装更新。

## 6. 回传最小结果

保留原始报告、Word、截图和备份；只回传设备角色、build_id／ZIP SHA、Windows／架构／WebView2、PowerShell／Word版本、下表结论和证据别名。不要公开机器名、SID、用户名路径、真实正文／照片、口令或密钥。首失败与复验分开，不覆盖原现场。

| 项目 | 实际结果／错误码／证据别名 | 状态 | 执行者／教师确认 |
| --- | --- | --- | --- |
| ZIP／PS1身份、只读预检、策略／签名 | | 未执行 | |
| 普通启动／新根建档／明暗／正常重开 | | 未执行 | |
| 周本人来源／人工覆盖与留空／刷新 | | 未执行 | |
| 保存／明确确认／历史／切周关窗接续 | | 未执行 | |
| 旧确认导出保留当前dirty稿／原生重试 | | 未执行 | |
| 日计划／三类观察／图片与历史相关回归 | | 未执行 | |
| 明文／加密／取消／错口令／坏包 | | 未执行 | |
| 替换恢复／保护包再恢复／新进程接续 | | 未执行 | |
| 首次页直接恢复／空档案保护包 | | 未执行 | |
| WW1–WW5与相关日／观察Word逐页 | | 未执行 | |
| 教师本人使用与新Word确认 | | 未执行 | |

状态用“通过／失败／受阻／未知／未执行”。Win10、WPS、其它显示条件、干净机、长根206、历史无guard缺口按既有未验保留；本次不追测的项目不能写成修复／通过。静态、目标预检、普通运行、Word页检、教师确认及正式发行分别判断。
