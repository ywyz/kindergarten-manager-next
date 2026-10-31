# Windows 11 内部便携候选：目标预检与使用验收

更新：2026-10-31。**目标电脑尚未操作，下面均为步骤和预期，不是通过记录。** D 起草的英文说明已保留为私有审核证据；D 停写后由 Codex 中文审校，本文件现归 Codex，预检脚本仍归 D。

## 1. 本次使用的文件

完整目录包和 ZIP 的实际身份以[构建结果](desktop-windows11-portable-result.md)及[独立核查](desktop-windows11-portable-review.md)为准。只使用本轮新候选，不拿旧 r03 或单个 EXE 代替。

| 项目 | 本轮值 |
| --- | --- |
| ZIP | `build/desktop-e14-win11-r03/dist/KGNext-E14-win11-r01.zip`；逻辑文件名保留 r01，实际使用 r03 物理根 |
| ZIP SHA-256 | `0a1b9c0b55612de889e621f70ed1374d8e792d3755d9fce1eadf17b7b6532470` |
| build_id | `5babc817-5b2a-466b-b382-36cffa02cace` |
| 数据库版本 | `20261025_0006_local_game_observations` |
| 产品目录 | `KGNext-E14`，须保留全部 `_internal`、资源和许可证 |
| 外层文件 | `README-KGNext-E14-win11-r01.txt`、`package-files.json`、`SHA256SUMS.txt` |
| 另带预检脚本 | [check_windows11_target.ps1](../../desktop/check_windows11_target.ps1)，放在解压目录外 |
| 预检脚本 SHA-256 | `d7cdb39576a83ad76c71490b7416fa47e41f312acd8b7f1d8ca67bbc5ed1caaf` |
| 合成种子备份 | `build/desktop-e14-win11-r03/handoff-synthetic/`，完整四文件；身份和口令见构建结果 §9.2，不放进程序 ZIP，不带 DPAPI |

这是**未签名内部测试候选**，尚未证明目标机能运行。当前开发机已完成 PS7 只读预检，不能填入下面的目标回执；Windows 自带 PS5.1 仅解析通过，实际文件执行受策略阻止，仍未验。目标无需开发用 Python、Node、venv 或 node_modules；使用 Windows 自带 PowerShell 和实际 WebView2 Runtime。证书申请、真实 AI、WebDAV、安装更新和公开发行分开处理。

## 2. 先核包，再只读预检

以下命令在目标电脑普通权限 PowerShell 中执行。把前两项改为实际保存位置；先核 ZIP 的外部已知 SHA，再解压。所有测试放进新的自有目录，数据和凭据子目录交应用创建，不提前创建凭据目录。

```powershell
$zip = (Resolve-Path -LiteralPath '<本轮 ZIP 的完整路径>').Path
$check = (Resolve-Path -LiteralPath '<另存的 check_windows11_target.ps1 完整路径>').Path
$expectedSha = '0a1b9c0b55612de889e621f70ed1374d8e792d3755d9fce1eadf17b7b6532470'
$buildId = '5babc817-5b2a-466b-b382-36cffa02cace'
$expectedCheckSha = 'd7cdb39576a83ad76c71490b7416fa47e41f312acd8b7f1d8ca67bbc5ed1caaf'
if ((Get-FileHash -LiteralPath $check -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedCheckSha) {
    throw '预检脚本与已审核内容不符，停止。'
}
if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedSha) {
    throw 'ZIP 与本轮身份不符，停止。'
}
$trial = Join-Path $env:TEMP ('KgmWin11-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
if (Test-Path -LiteralPath $trial) { throw '测试目录已存在，停止。' }
New-Item -ItemType Directory -Path $trial -ErrorAction Stop | Out-Null
$extract = Join-Path $trial 'candidate'
$data = Join-Path $trial 'data'
$credentials = Join-Path $trial 'credentials'
Expand-Archive -LiteralPath $zip -DestinationPath $extract
& $check -ExtractRoot $extract -ArchivePath $zip `
  -ExpectedArchiveSha256 $expectedSha -ExpectedBuildId $buildId `
  -ExpectedDatabaseRevision '20261025_0006_local_game_observations' `
  -DataRoot $data -CredentialRoot $credentials `
  -ReportPath (Join-Path $trial 'preflight.json')
$LASTEXITCODE
```

保留 `$trial` 对应目录供本轮继续使用；它不是需要公开回传的路径。不要把 ZIP、脚本或报告放进解压目录，解压根应恰好是产品目录和三份外层文件。

预检检查实际系统、原生架构、WebView2、可读安全策略、文件集与 SHA、构建身份、PE 和签名状态、默认数据是否已存在，以及输出隔离。退出 `0` 是本机只读检查完成，`1` 是明确失败，`2` 是不完整或未知；任何值均不能单独证明系统会放行应用。签名状态和真实启动分别记录。脚本的 `scope=self_current_machine_only` 仅表示执行它的这一台电脑；回执另注明 `开发机` 或 `目标1`。

有未知、ARM64、缺组件、文件不符或权限问题时，保留结果并先停止相关步骤，不自行安装组件或把兼容层当作已验证。WebView2 需检测 Runtime；Edge 浏览器存在不作替代，`pv=0.0.0.0` 不算安装。[微软检测说明](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)。

### 脚本被策略阻止时

保留实际错误。不要用 Bypass、解除来源标记、粘贴整段脚本改执行方式、改名、管理员重试或修改策略绕过。

- 设置 → 系统 → 系统信息／关于：记录 Windows 版本和系统类型；无法确定原生架构就记未知。
- 设置中查找已安装应用／系统组件里的 WebView2 Runtime；看不到就记未确认，不把 Edge 版本当 Runtime 版本。
- Windows 安全中心 → 应用和浏览器控制 → Smart App Control：只读实际状态，不切换。
- 组织策略／WDAC 无可读结果时记未知；“没有看到策略”不等于关闭。
- 文件属性 → 数字签名可查看主程序的实际状态；完整 PE 清点仍记未完成。
- 默认 `%LOCALAPPDATA%\KindergartenManager\data` 和 `credentials` 只看是否存在，不打开数据库、凭据或旧备份。

手动查看结果不补成脚本全项通过。当前开发机已知 SAC4551，本轮不在这台机器试跑候选；目标机若首次拦截，也停在该结果，不换目录／名称／hash 反复试。

## 3. 普通入口与业务

预检结果可核对、目标架构适用后，用相同的新合成根启动普通入口：

```powershell
$exe = Join-Path $extract 'KGNext-E14\KGNext-E14.exe'
& $exe --data $data --credential-root $credentials
```

不加 selftest，不直接改数据库。默认数据已存在也不用它做试验；仅在确认默认位置全新、单独安排的步骤中另验双击默认入口。本轮不会替用户覆盖真实档案。

| 步骤 | 操作与应看到的结果 |
| --- | --- |
| 首次页 | 用合成教师、班级、学期建档；另一个独立新根验证首次页直接恢复，无需临时档案。 |
| 日计划 | 新建、编辑、保存、离开后重开；已保存正文、日期和表头一致。导出按日计划已保存快照规则，不借导出静默保存未提交稿。 |
| 三类观察 | 分别创建记录，真实原生选取本人制作的合成图片；排序、说明、保存、历史预览／恢复，再重开核对同版本文字和照片。不要只用桥接替身。 |
| 原图独立性 | 应用保存成功后，可移动本轮自有外部合成原图，再检查受管理照片仍可用；不动真实照片。 |
| 无 AI 手工业务 | 不填真实密钥也能保存、查看历史、图片和 Word。保存合成密钥时也不触发供应商请求。 |
| 关闭接续 | 正常关闭本轮窗口，新进程用相同两根重开，内容／历史／图片一致；不删运行锁、不全局 kill。 |

第二普通实例若报告当前档案已占用，记真实行为，不强开；只关闭本轮自己能明确识别的窗口。保存失败留页，未知结果不猜成功。

## 4. 真实选图与另存为

依次实际操作：取消选图、成功导入；取消另存为、成功保存；在自己导出的测试文件被 Word 占用时按当前确认契约尝试保存，解除占用后由用户明确重试。各步骤保留正文和照片、正确显示取消／失败，不重复发 AI。

日计划和观察的覆盖确认／拒绝按现有各自契约核对，不为测试强制覆盖。不把取消当 I/O 失败；若占用未触发失败，记该分支未覆盖。遇到 `unknown`，先核实际文件再决定重试，不自动重开保存。观察导出须先成功保存本次编辑再固定版本；保存失败不能交付旧稿冒充本次编辑。

## 5. 完整备份、替换与保护包接续

1. 在本轮合成根准备可辨认的“原工作 A”，包括日计划、三类观察、照片说明及历史。先保存，再从正常界面分别创建明文和加密 `.kgmbackup`，保存到 `$trial` 下单独的 `backups` 目录，放在数据／凭据根之外。
2. 口令只供本轮测试，私下保管；不输入口令不能静默降成明文。外部 Word 和外部原图不属于应用备份，另行保存。
3. 改成可辨认的“新工作 B”，保存。正常 UI 选 A 的备份，先完整校验和预览，再明确确认替换；取消预览不替换。
4. 确认完成后，核 A 的正文、配置、三类观察、各历史版本、图片顺序／说明。记录界面给出的恢复前保护包，保留完整文件。工程位置为数据根旁的 `data.restore-guard/<本次操作>/pre-restore.kgmbackup`；仅查本轮自有根，不翻真实资料。
5. 在恢复后的新窗口编辑、保存并正常退出；全新进程重开，核新工作仍在。再经普通 UI 预览并恢复刚才的保护包，找回替换前的 B。每次恢复产生的保护包都保留，不自动清理。
6. 加密包分别验证正确口令、错误口令、取消；用另存的合成损坏副本测试坏包，不能破坏唯一原包。首次页直接恢复时也应保留空业务档案的保护包。

失败、取消、口令错误、预览过期或恢复未明确完成时，不把进度条当成功；核当前档案可继续使用，保护包仍在。异常现场私下保留，反馈最小阶段／错误，不继续覆盖真实数据。

### 换机凭据

只交接合成 `.kgmbackup`，不搬数据库家族、DPAPI、凭据根或可携带主密钥。目标没有原 Windows 解密材料时，保留库内密文及身份，显示需要重填；手工保存、历史、图片和 Word 仍应可用。若验证重填，仅用合成无效密钥且不发请求；同机控制、目标换机结果分栏。真实个人档案迁移以后由用户在界面预览、确认，不能由代理代替覆盖。

## 6. 新 Word 样例：逐页检查八份

样例必须来自本轮候选的真实 UI／原生另存为；若在当前源码做同样步骤，单列“源码”，不能记为新包或目标结果。没有 Microsoft Word 时，结构核对与 Word 逐页分别记未验，旧样本或 XML 不代替。

| 编号 | 代表样例 | 逐页要核对 |
| --- | --- | --- |
| W1 | 日计划单日，含可选缺项 | 日期／班级／学期／已保存正文和缺项处理正确，无多余空页。 |
| W2 | 日计划多日合并，长正文、长园所名 | 实际选集与日期顺序、各份起始页和标题正确，换行和分页完整。 |
| W3 | 公共区域观察，0 图 | 文字、表格完整，无空图片占位或异常空页。 |
| W4 | 室内观察，1 张竖图 | 方向、比例、说明和位置正确，无拉伸。 |
| W5 | 户外观察，2 张横竖混图 | 两图均在，方向／顺序／说明一致。 |
| W6 | 观察，3 图与长正文 | 图文不裁切、不重叠，分页不破坏照片。 |
| W7 | 混合类型多份观察，覆盖 5 图 | 实际手选清单、手调顺序与 Word 相同，无漏份／漏图／重复。 |
| W8 | 观察保存顺序与长文 | 编辑后立即导出，先成功保存再固定版本；Word 与本次成功保存快照一致，失败不交旧版。 |

每份记录来源版本／build_id、实际文件别名、页数、Word 版本、字体和问题页。检查标题／签名、表格边框、页眉页脚、中文字体、图片方向及最后一页；记录是自动核对、人工 Word 观察还是教师本人确认。教学内容质量由教师判断，工程代理不代签。

## 7. 最小回执

原始报告、截图、Word、备份和口令私下保留。公开回执只用设备角色和证据别名，不含机器名、SID、用户名、完整路径、真实正文、照片或密钥。失败首现场保留；后续重试另列，不覆盖首失败。

| 项目 | 设备角色 | 执行者（自动／人工／教师） | 版本／build_id | 实际结果 | 状态 | 错误码／证据别名 | 教师确认 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OS／原生架构／WebView2／策略 | | | | | | | |
| ZIP／解压文件／身份／PE 签名 | | | | | | | |
| 普通入口／新根／首次档案 | | | | | | | |
| 日计划／三类观察／图片／历史 | | | | | | | |
| 原生选图／取消／成功／占用／重试 | | | | | | | |
| 明文／加密备份 | | | | | | | |
| 校验／预览／取消／替换／保护包再恢复 | | | | | | | |
| 新窗口编辑／全新进程重开／关闭 | | | | | | | |
| 换机重填／无 AI 手工业务 | | | | | | | |
| Word W1–W8 逐页 | | | | | | | |

状态用“通过／失败／受阻／未知／未执行”，只填实际观察。**目前所有目标结果为空；静态、目标普通运行、Word、教师体验、签名及发行分别判断。**
