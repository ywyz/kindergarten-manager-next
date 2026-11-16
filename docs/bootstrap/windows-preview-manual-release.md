# Windows 预览版：手动打包、签名与在线更新发布

2026-11-16：用户已完成本版打包、签名和公开发布。初版草稿读取使用 tag 接口返回 404，逐行执行又未在报错后停下，导致后续验证标识缺失；公开发布实际成功。此处已修正草稿按 ID 读取及整段遇错停止，原失败记录保留。**本版已发布，不要重跑创建／上传命令。** 本文保留本版参数用于复核和后续流程参考，不代表真实机更新验收通过。

后续适用轮次在同一个 **Windows PowerShell 5.1** 窗口按顺序执行各段，**包含每段开头的 `. {` 和末尾的 `}` 一起复制执行**。每段以阶段标识衔接，异常中止当前整段，后续段拒绝缺失的前置结果。保留输出目录；SimplySign 保持登录，使用当前 Windows 用户，不需要管理员权限。不需要运行安装器或关闭业务窗口来完成这些打包步骤。

本轮版本固定 `0.1.0-listening-test.20261116`，源码固定 `ddd97086a8c784c5c33bf390bab903f5b9f36f58`。已有 `-manual` Release 保留，新完整发布使用不带该后缀的 tag。未来版本必须重新冻结、构建、审核和签名，不能只改下面的版本号或包内 JSON。

## 1. 初始化并核对输入

`preview-ed25519.dpapi` 是原在线更新签名密钥，只在原 Windows 用户下由本机工具使用。它与 SimplySign 证书不同，不上传、不打印内容、不生成替代密钥。

```powershell
. {
$ErrorActionPreference = 'Stop'
$manualStage = 0
$repo = 'C:\Users\yw980\code\kindergarten-manager-next'
$base = 'C:\Users\yw980\KGNext-BuildEvidence-20261116'
$src = "$base\source"
$python = "$src\desktop\.venv-d1\Scripts\python.exe"
$originalApp = "$base\release-stage\app\KindergartenManager"
$updater = "$base\release-stage\updater\KindergartenManagerUpdater"
$assemble = 'D:\kgm-release-20261115\release-tools\assemble-signed-preview.py'
$iscc = 'D:\kgm-release-20261115\release-tools\inno\ISCC.exe'
$signtool = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe'
$gh = 'C:\Program Files\GitHub CLI\gh.exe'
$key = 'C:\Users\yw980\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\KindergartenManagerReleaseSigning\preview-ed25519.dpapi'
$thumb = '7F4512CC89CB6D814E5EDF9335DB086C8D13BB2B'
$version = '0.1.0-listening-test.20261116'
$previous = '0.1.0-listening-test.20261115'
$revision = '20261112_0021_local_term_name_changes'
$buildId = '936eb558-c777-4cb0-bf4c-95c3cf66798f'
$commit = 'ddd97086a8c784c5c33bf390bab903f5b9f36f58'
$tag = "v$version"
$githubRepo = 'ywyz/kindergarten-manager-next'
$env:APP_DISABLE_DOTENV = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = "$src\desktop;$src\backend"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

function Check-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed: exit $LASTEXITCODE" }
}
function Check-Hash([string]$Path, [string]$Expected) {
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Expected) {
        throw "SHA256 mismatch: $Path"
    }
}
function Check-Tree([string]$Root, [string]$ManifestPath) {
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $items = @(Get-ChildItem -LiteralPath $Root -Recurse -Force)
    if (@($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw "Reparse point in input: $Root"
    }
    if (@($items | Where-Object { -not $_.PSIsContainer }).Count -ne $manifest.files.Count) {
        throw "File count changed: $Root"
    }
    foreach ($entry in $manifest.files) {
        $path = Join-Path $Root $entry.path
        if ((Get-Item -LiteralPath $path).Length -ne $entry.size) { throw "Size changed: $path" }
        Check-Hash $path $entry.sha256
    }
}
function Check-Certum([string]$Path) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or
        $signature.SignerCertificate.Thumbprint -ne $thumb -or
        $null -eq $signature.TimeStamperCertificate) { throw "Signature invalid: $Path" }
}
foreach ($path in @($python, $assemble, $iscc, $signtool, $gh, $key)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing: $path" }
}
$sourceHead = & git -C $src rev-parse HEAD
Check-Exit 'Read source commit'
if ($sourceHead -ne $commit) { throw 'Unexpected frozen source commit' }
$sourceChanges = & git -C $src status --porcelain --untracked-files=no
Check-Exit 'Read source status'
if ($sourceChanges) { throw 'Tracked frozen source changed' }
Check-Hash $assemble '5C3E23A7FD61DB8A66A89DF0E0D15C4E43A6CF7C553D329B130E8B331C1C0B1A'
Check-Hash "$base\signed-app-manifest.json" 'D84A646374F038DA1BBEF388E255E07B6D6FF9497A293D2C7ADE34C9654A8F85'
Check-Hash "$base\signed-updater-manifest.json" 'DCA81E723FF628ADA7C0902FFD3202EC975DD45B12D8CD1E37D8909E05CC0CAF'
Check-Tree $originalApp "$base\signed-app-manifest.json"
Check-Tree $updater "$base\signed-updater-manifest.json"
Check-Certum "$originalApp\KindergartenManager.exe"
Check-Certum "$updater\KindergartenManagerUpdater.exe"
if (-not (Get-Item -LiteralPath "Cert:\CurrentUser\My\$thumb").HasPrivateKey) { throw 'Signing certificate unavailable' }
if ((Get-AuthenticodeSignature -LiteralPath $signtool).Status -ne 'Valid') { throw 'SignTool signature invalid' }
& $gh auth status
Check-Exit 'GitHub authentication'
$existing = & git -C $repo ls-remote origin "refs/tags/$tag" "refs/tags/$tag^{}"
Check-Exit 'Check existing tag'
if ($existing) { throw 'Target tag already exists; do not overwrite it' }

$run = Join-Path 'C:\Users\yw980' ('KGNext-Manual-Release-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,6))
New-Item -ItemType Directory -Path $run -ErrorAction Stop | Out-Null
$app = "$run\KindergartenManager"
$assets = "$run\assets"
$notes = "$run\release-notes.md"
Copy-Item -LiteralPath $originalApp -Destination $app -Recurse
Check-Tree $app "$base\signed-app-manifest.json"
$notesText = @'
Windows 11 x64 签名预览 0.1.0-listening-test.20261116

冻结源码：ddd97086a8c784c5c33bf390bab903f5b9f36f58。
完善左侧导航、工作台日历和未完成待办、日周计划及观察倾听阅读界面；修复教案适龄和倾听流程，支持教师核对后采用幼儿原话补写。

本版同时提供签名安装器、完整在线更新 ZIP、Ed25519 签名清单和 SHA256SUMS。
20261115 签名预览可通过应用内预览渠道检查此版本；已装 20261116 手动版无需重复更新。
20261114 或更早版本请先保存并退出，再手动运行安装器以更新独立更新器。
源码和自动检查结果不代替教师真机验收，安装替换和重启结果待实际验证。
'@
[IO.File]::WriteAllText($notes, $notesText, $utf8)
Write-Host "This run: $run"
$manualStage = 1
}
```

## 2. 打在线更新 ZIP 并签署更新清单

使用原密钥，只修改刚复制的新目录。工具会签署清单、验证签名，并解压核对包内全部文件；再额外核对 ZIP 整体摘要和大小。不要执行工具的 `config` 子命令。

```powershell
. {
if ($manualStage -ne 1) { throw 'Initialization not completed' }
$ErrorActionPreference = 'Stop'
$manualStage = 0
& $python $assemble --key $key package `
    --app $app --output $assets --verified "$run\verified" `
    --notes $notes --version $version --current-version $previous `
    --source-revision $revision
Check-Exit 'Create and verify online update package'
$zip = "$assets\KindergartenManager-windows-x64.zip"
$metadata = "$assets\update-manifest-windows-x64.json"
$manifest = Get-Content -LiteralPath $metadata -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.key_id -ne 'kgm-preview-77669a93b07bf22b' -or
    $manifest.payload.version -ne $version -or $manifest.payload.build_id -ne $buildId -or
    $manifest.payload.package_url -ne "/$githubRepo/releases/download/$tag/KindergartenManager-windows-x64.zip" -or
    $manifest.payload.package_size -ne (Get-Item -LiteralPath $zip).Length) { throw 'Update identity or size mismatch' }
Check-Hash $zip $manifest.payload.package_sha256
Check-Tree $originalApp "$base\signed-app-manifest.json"
Write-Host 'Online package and signed manifest verified'
$manualStage = 2
}
```

本轮源、目标数据库 revision 相同。未来跨 revision 时必须另对每个实际支持的源版本／revision 验证迁移；本工具中的目标 revision 自检不能代替旧版本兼容验证。

## 3. 重新制作并用 SimplySign 签署安装器

应用及更新器沿用已核对签名；Inno 此步调用 Certum 签署新 Setup 和卸载器，包含 RFC3161 时间戳。`$q`、`$f` 是 Inno 占位符，必须保留，不改成普通双引号。

```powershell
. {
if ($manualStage -ne 2) { throw 'Online package verification not completed' }
$ErrorActionPreference = 'Stop'
$manualStage = 0
$signCommand = '$q' + $signtool + '$q sign /sha1 ' + $thumb + ' /fd sha256 /tr http://time.certum.pl/ /td sha256 $f'
& "$src\.github\scripts\build-windows11-signed-preview-installer.ps1" `
    -AppSource $app -UpdaterSource $updater -OutputDir "$run\installer" `
    -AppVersion $version -NumericVersion '0.1.0.0' -BuildId $buildId `
    -IsccPath $iscc -CertumSignCommand $signCommand
$setup = "$run\installer\KGNext-Win11-x64-Preview-Setup.exe"
Check-Certum $setup
Copy-Item -LiteralPath $setup -Destination "$assets\KGNext-Win11-x64-Preview-Setup.exe"
$assetNames = @('KGNext-Win11-x64-Preview-Setup.exe', 'KindergartenManager-windows-x64.zip', 'update-manifest-windows-x64.json', 'SHA256SUMS.txt')
$sumLines = foreach ($name in $assetNames | Where-Object { $_ -ne 'SHA256SUMS.txt' }) {
    (Get-FileHash -LiteralPath "$assets\$name" -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + $name
}
[IO.File]::WriteAllText("$assets\SHA256SUMS.txt", ($sumLines -join "`n") + "`n", $utf8)
$localAssets = foreach ($name in $assetNames) {
    $file = Get-Item -LiteralPath "$assets\$name"
    [pscustomobject]@{ name=$name; size=$file.Length; sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
}
$localAssets | ConvertTo-Json | Set-Content -LiteralPath "$run\local-assets.json" -Encoding UTF8
Check-Tree $updater "$base\signed-updater-manifest.json"
$localAssets | Format-Table
$manualStage = 3
}
```

这是重新签名的安装器，摘要与已发布 `-manual` 安装器不同是预期结果；原安装器不被覆盖。此步不安装、不启动应用。

## 4. 上传草稿并下载复核

只上传下面四项。密钥、证据目录、data、credentials 不进入附件。tag 固定指向实际产物的冻结源码，不使用当前文档提交代替。

草稿尚未建立公开 tag 时，不使用 `/releases/tags/{tag}` 查询；先从有权限的 Release 列表取得唯一 ID，再用 `/releases/{id}` 查询。[GitHub Release 列表与草稿权限](https://docs.github.com/en/rest/releases/releases#list-releases)

```powershell
. {
if ($manualStage -ne 3) { throw 'Installer and local assets not completed' }
$ErrorActionPreference = 'Stop'
$manualStage = 0
$verifiedReleaseId = $null
foreach ($proof in @('verified-draft.json','verified-release-gate.json')) {
    if (Test-Path -LiteralPath "$run\$proof") { throw 'Prior verification evidence exists; preserve it and inspect the current release' }
}
$uploadArgs = @('release','create',$tag,'--repo',$githubRepo,'--target',$commit,'--title',"Windows 11 签名预览 $version",'--draft','--prerelease','--latest=false','--notes-file',$notes)
foreach ($name in $assetNames) { $uploadArgs += "$assets\$name" }
& $gh @uploadArgs
Check-Exit 'Upload draft release'
$releasePagesRaw = & $gh api --paginate --slurp "repos/$githubRepo/releases?per_page=100"
Check-Exit 'List releases including drafts'
$releasePages = $releasePagesRaw | ConvertFrom-Json
$matchingDrafts = @(foreach ($page in @($releasePages)) {
    foreach ($item in @($page)) { if ($item.tag_name -ceq $tag) { $item } }
})
if ($matchingDrafts.Count -ne 1 -or -not $matchingDrafts[0].draft) { throw 'Expected exactly one matching draft' }
$draftId = [long]$matchingDrafts[0].id
if ($draftId -le 0) { throw 'Invalid draft ID' }
$draftRaw = & $gh api "repos/$githubRepo/releases/$draftId"
Check-Exit 'Read draft release'
$draft = $draftRaw | ConvertFrom-Json
if ($draft.id -ne $draftId -or -not $draft.draft -or -not $draft.prerelease -or $draft.tag_name -ne $tag -or $draft.target_commitish -ne $commit) { throw 'Unexpected draft identity' }
if (@($draft.assets).Count -ne $assetNames.Count) { throw 'Unexpected asset count' }
foreach ($local in $localAssets) {
    $remote = @($draft.assets | Where-Object { $_.name -ceq $local.name })
    if ($remote.Count -ne 1 -or $remote[0].size -ne $local.size -or $remote[0].digest -ne "sha256:$($local.sha256)") { throw "Remote asset mismatch: $($local.name)" }
}
$downloadDir = "$run\download-verification"
New-Item -ItemType Directory -Path $downloadDir | Out-Null
$downloadArgs = @('release','download',$tag,'--repo',$githubRepo,'--dir',$downloadDir)
foreach ($name in $assetNames) { $downloadArgs += @('--pattern',$name) }
& $gh @downloadArgs
Check-Exit 'Download draft assets'
foreach ($local in $localAssets) { Check-Hash "$downloadDir\$($local.name)" $local.sha256 }
Check-Certum "$downloadDir\KGNext-Win11-x64-Preview-Setup.exe"
$draftRaw | Set-Content -LiteralPath "$run\verified-draft.json" -Encoding UTF8
$verifiedReleaseId = $draft.id
$verifiedGate = [ordered]@{ schema=1; release_id=$verifiedReleaseId; tag=$tag; commit=$commit; repo=$githubRepo; assets=$localAssets }
$verifiedGate | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$run\verified-release-gate.json" -Encoding UTF8
Write-Host 'All draft assets match the verified local files'
$manualStage = 4
}
```

## 5. 公开发布

这是实际公开发布命令。仅在第 4 段全部成功后运行，保持预发布、非 Latest，不修改既有 Release。若上传中途失败，保留草稿并核对，不盲目重跑创建或使用 `--clobber`。

```powershell
. {
if ($manualStage -ne 4) { throw 'Draft verification not completed' }
$ErrorActionPreference = 'Stop'
$manualStage = 0
$gate = Get-Content -LiteralPath "$run\verified-release-gate.json" -Raw -Encoding UTF8 | ConvertFrom-Json
if ($gate.schema -ne 1 -or ($gate.release_id -isnot [int] -and $gate.release_id -isnot [long]) -or $gate.release_id -le 0 -or $gate.tag -ne $tag -or $gate.commit -ne $commit -or $gate.repo -ne $githubRepo -or @($gate.assets).Count -ne $assetNames.Count) { throw 'Draft verification missing or mismatched' }
$verifiedReleaseId = [long]$gate.release_id
foreach ($name in $assetNames) {
    $record = @($gate.assets | Where-Object { $_.name -ceq $name })
    if ($record.Count -ne 1) { throw 'Gate asset set mismatch' }
    Check-Hash "$assets\$name" $record[0].sha256
    if ((Get-Item -LiteralPath "$assets\$name").Length -ne $record[0].size) { throw 'Local asset size changed' }
}
$localAssets = @($gate.assets)
$latestRaw = & $gh api "repos/$githubRepo/releases/$verifiedReleaseId"
Check-Exit 'Recheck draft before publishing'
$latest = $latestRaw | ConvertFrom-Json
if ($latest.id -ne $verifiedReleaseId -or -not $latest.draft -or -not $latest.prerelease -or $latest.tag_name -ne $tag -or $latest.target_commitish -ne $commit -or @($latest.assets).Count -ne $assetNames.Count) { throw 'Draft changed' }
foreach ($local in $localAssets) {
    $remote = @($latest.assets | Where-Object { $_.name -ceq $local.name })
    if ($remote.Count -ne 1 -or $remote[0].size -ne $local.size -or $remote[0].digest -ne "sha256:$($local.sha256)") { throw 'Draft asset changed' }
}
$publishRaw = & $gh api --method PATCH "repos/$githubRepo/releases/$verifiedReleaseId" -F draft=false -F prerelease=true -f make_latest=false
Check-Exit 'Publish release'
$publishResponse = $publishRaw | ConvertFrom-Json
if ($publishResponse.id -ne $verifiedReleaseId -or $publishResponse.draft -or -not $publishResponse.prerelease -or $publishResponse.tag_name -ne $tag) { throw 'Unexpected publish response' }
$publishedRaw = & $gh api "repos/$githubRepo/releases/tags/$tag"
Check-Exit 'Read published release'
$published = $publishedRaw | ConvertFrom-Json
if ($published.draft -or -not $published.prerelease -or $published.id -ne $verifiedReleaseId) { throw 'Unexpected published state' }
$tagRaw = & $gh api "repos/$githubRepo/git/ref/tags/$tag"
Check-Exit 'Read published tag'
$tagRef = $tagRaw | ConvertFrom-Json
if ($tagRef.object.type -ne 'commit' -or $tagRef.object.sha -ne $commit) { throw 'Unexpected tag target' }
$publishedRaw | Set-Content -LiteralPath "$run\published-release.json" -Encoding UTF8
Write-Host "Published: $($published.html_url)"
Write-Host "Evidence: $run"
$manualStage = 5
}
```

执行后将最后的 Release 链接和 `Evidence` 路径交给 Codex，继续独立检查公开下载、生产解析器的版本／资产／签名绑定。不要把“发布成功”写成真实安装更新成功。

验证应用内更新请用已安装 `20261115` 且带独立更新器的环境，选择预览渠道；已安装 `20261116` 不会重复升级到同版本。`20261114` 及更早版本先手动安装以更新 helper。真实机安装、数据保留、关闭握手、替换与重启均由实际结果记录。

## 后续每版的固定要求

所有后续安装包发布都同时准备签名 Setup、完整更新 ZIP、Ed25519 签名清单和 SHA256SUMS。先完成资产，再公开可被客户端识别的 tag；不以只有安装器的标准版本发布代替完整发行。

应用与 helper 必须携带匹配且兼容旧安装的公钥和协议。在线 ZIP 只替换 app；更改 helper 或轮换信任需单独验证过渡路径。保留原密钥，不能每版重新生成。

新版本重做源码冻结、依赖核对、前端／Python 构建、法律材料及公开配置准备、PE 签名、静态／运行审核，再按本文的组装、安装器、草稿和发布顺序执行。这里的精确路径、版本、摘要和 build ID 仅适用于本轮，不是通用新版本构建参数。
