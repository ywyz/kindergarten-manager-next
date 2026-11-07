<#
Compile and exercise the unsigned per-user one-to-one-listening test installer
on a disposable GitHub windows-2022 runner.

The already-built KGNext-E14 onedir package and the existing static validation
summary are inputs; this script never rebuilds the package, never launches the
packaged application or a helper, never installs/downloads WebView2, never
touches a real teacher profile, and never signs the installer.

Silent install is used only to verify the installed payload, Start Menu
shortcut arguments and that a synthetic data/credential tree survives
uninstall. The runner is Windows Server and is not Windows 11 runtime evidence.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$BuildRoot,
    [Parameter(Mandatory = $true)][string]$ValidationSummary,
    [Parameter(Mandatory = $true)][string]$InstallerRoot,
    [Parameter(Mandatory = $true)][string]$RunId,
    [Parameter(Mandatory = $true)][string]$RunAttempt,
    [string]$Repository = $env:GITHUB_REPOSITORY,
    [string]$CommitSha = $env:GITHUB_SHA
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedRevision = '20261107_0010_local_listening_ai'
$ExpectedBranch = 'refs/heads/codex/desktop-one-to-one-listening'
$InstallerName = 'KGNext-Listening-Win11-x64-Setup.exe'
$IdentityName = 'installer-identity.json'
$SumsName = 'SHA256SUMS.txt'
$ShortcutFolder = 'Kindergarten Manager 一对一倾听测试版'
$ShortcutName = '一对一倾听测试版.lnk'

function Fail {
    param([string]$Message)
    throw $Message
}

function Assert-File {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Fail "Missing ${Label}: $Path"
    }
}

function Assert-Dir {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        Fail "Missing ${Label}: $Path"
    }
}

function Get-FullPath {
    param([string]$Path, [string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        Fail "Empty path for ${Label}"
    }
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-Under {
    param([string]$Path, [string]$Root)
    $full = [System.IO.Path]::GetFullPath($Path)
    $base = [System.IO.Path]::GetFullPath($Root).TrimEnd(
        [char[]]@('\', '/')
    )
    return (
        $full.Equals($base, [System.StringComparison]::OrdinalIgnoreCase) -or
        $full.StartsWith(
            $base + [System.IO.Path]::DirectorySeparatorChar,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    )
}

function Assert-Under {
    param([string]$Path, [string]$Root, [string]$Label)
    if (-not (Test-Under $Path $Root)) {
        Fail "${Label} must be inside ${Root}: $Path"
    }
}

function Invoke-External {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$LogPath
    )
    & $FilePath @Arguments 2>&1 | Tee-Object -FilePath $LogPath
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Fail "Command failed ($code): $FilePath $($Arguments -join ' ')"
    }
}

function Get-PayloadMap {
    param([string]$Root, [switch]$ExcludeUninstaller)
    $map = @{}
    $total = [long]0
    foreach ($file in Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction Stop) {
        $relative = [System.IO.Path]::GetRelativePath($Root, $file.FullName).Replace('\', '/')
        if ($ExcludeUninstaller -and $relative -match '^unins[0-9]+\.(exe|dat|msg)$') {
            continue
        }
        $map[$relative] = [ordered]@{
            size = [long]$file.Length
            sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $total += [long]$file.Length
    }
    return [pscustomobject]@{
        files = $map
        bytes = $total
        count = [int]$map.Count
    }
}

function Get-PayloadTreeDigest {
    param([hashtable]$Map)
    $rows = @(
        $Map.Keys | Sort-Object | ForEach-Object {
            [ordered]@{
                path = $_
                size = [long]$Map[$_].size
                sha256 = [string]$Map[$_].sha256
            }
        }
    )
    $json = ConvertTo-Json -InputObject $rows -Depth 5 -Compress
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($json)
        return [System.BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-FileSha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

if ($RunId -notmatch '^[0-9]+$' -or $RunAttempt -notmatch '^[0-9]+$') {
    Fail 'RunId and RunAttempt must be numeric'
}
if ($env:GITHUB_ACTIONS -ne 'true') {
    Fail 'This installer script is restricted to ephemeral GitHub Actions runners'
}
if ($env:GITHUB_EVENT_NAME -ne 'workflow_dispatch') {
    Fail 'The listening installer path only accepts workflow_dispatch'
}
if ($env:GITHUB_REF -ne $ExpectedBranch) {
    Fail "The listening installer path only accepts $ExpectedBranch"
}
if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    Fail 'RUNNER_TEMP is required'
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    Fail 'LOCALAPPDATA is required'
}

$repo = Get-FullPath $RepoRoot 'RepoRoot'
$build = Get-FullPath $BuildRoot 'BuildRoot'
$summaryPath = Get-FullPath $ValidationSummary 'ValidationSummary'
$installerRoot = Get-FullPath $InstallerRoot 'InstallerRoot'
$runnerTemp = Get-FullPath $env:RUNNER_TEMP 'RUNNER_TEMP'
$buildLeaf = "desktop-e14-weekly-ci-$RunId-$RunAttempt"
$expectedBuild = Join-Path $repo ("build\" + $buildLeaf)
if (-not $build.Equals($expectedBuild, [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail "BuildRoot must be the current run package root: $expectedBuild"
}
Assert-Dir $build 'current build root'
Assert-Under $installerRoot $runnerTemp 'InstallerRoot'
if (Test-Path -LiteralPath $installerRoot) {
    Fail "InstallerRoot must be fresh: $installerRoot"
}
Assert-File $summaryPath 'existing static validation summary'

$commit = (& git -C $repo rev-parse HEAD 2>&1 | Out-String).Trim()
$tree = (& git -C $repo rev-parse 'HEAD^{tree}' 2>&1 | Out-String).Trim()
if ($commit -notmatch '^[0-9a-f]{40}$') {
    Fail "Could not resolve commit: $commit"
}
if ($tree -notmatch '^[0-9a-f]{40}$') {
    Fail "Could not resolve tree: $tree"
}
if (-not [string]::IsNullOrWhiteSpace($CommitSha) -and $CommitSha -ne $commit) {
    Fail "GITHUB_SHA does not match checkout HEAD: $CommitSha != $commit"
}
$trackedStatus = ((& git -C $repo status --porcelain=v1 --untracked-files=no 2>&1 | Out-String).Trim())
if (-not [string]::IsNullOrEmpty($trackedStatus)) {
    Fail "Tracked checkout is not clean: $trackedStatus"
}

$packageRoot = Join-Path $build 'package\KGNext-E14'
$mainExe = Join-Path $packageRoot 'KGNext-E14.exe'
$packageInfoPath = Join-Path $packageRoot 'package-info.json'
$buildIdentityPath = Join-Path $packageRoot '_internal\build_identity.json'
Assert-Dir $packageRoot 'verified package root'
Assert-File $mainExe 'package main EXE'
Assert-File $packageInfoPath 'package-info.json'
Assert-File $buildIdentityPath 'build_identity.json'

$summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding utf8 | ConvertFrom-Json
$packageInfo = Get-Content -LiteralPath $packageInfoPath -Raw -Encoding utf8 | ConvertFrom-Json
$buildIdentity = Get-Content -LiteralPath $buildIdentityPath -Raw -Encoding utf8 | ConvertFrom-Json

if ([string]$summary.commit -ne $commit -or [string]$summary.tree -ne $tree) {
    Fail 'validation summary commit/tree does not match checkout'
}
if ([string]$summary.workflow -ne 'windows11-weekly-validation') {
    Fail 'validation summary came from a different workflow'
}
if ([string]$summary.run_id -ne $RunId -or
    [string]$summary.run_attempt -ne $RunAttempt) {
    Fail 'validation summary run id/attempt does not match this run'
}
if (-not [string]::IsNullOrWhiteSpace($Repository) -and
    [string]$summary.repository -ne $Repository) {
    Fail 'validation summary repository does not match this run'
}
if ([string]$summary.build.build_root_name -ne $buildLeaf) {
    Fail 'validation summary build root does not match this run'
}
if ([string]$summary.build.build_id -ne [string]$packageInfo.build_id) {
    Fail 'validation summary/package-info build_id mismatch'
}
if ([string]$summary.build.database_revision -ne $ExpectedRevision) {
    Fail 'validation summary database revision is not the current 0010 head'
}
if ([string]$packageInfo.database_revision -ne $ExpectedRevision) {
    Fail 'package-info database revision is not the current 0010 head'
}
if ([string]$buildIdentity.database_revision -ne $ExpectedRevision) {
    Fail 'build_identity database revision is not the current 0010 head'
}
if ([string]$packageInfo.source_commit -ne $commit) {
    Fail 'package-info source commit does not match checkout'
}
if ([bool]$summary.static_validation.package.ok -ne $true -or
    [bool]$summary.static_validation.archive.ok -ne $true) {
    Fail 'existing package/archive static validation did not pass'
}
if ([bool]$summary.build.source_freeze_stable -ne $true) {
    Fail 'existing source freeze is not stable'
}
$summaryHash = Get-FileSha256 $summaryPath

$listeningRoot = Join-Path $packageRoot '_internal\app\assets\listening_templates'
Assert-File (Join-Path $listeningRoot 'manifest.json') 'listening template manifest'
$expectedListening = @('manifest.json')
foreach ($grade in @('small', 'middle', 'large')) {
    foreach ($domain in @('health', 'language', 'social', 'science', 'art')) {
        $relative = "v1/${grade}_${domain}.docx"
        Assert-File (Join-Path $listeningRoot $relative) 'listening template DOCX'
        $expectedListening += $relative
    }
}
$packageListening = @($packageInfo.listening_templates)
foreach ($relative in $expectedListening) {
    if ($packageListening -notcontains $relative) {
        Fail "package-info is missing listening template: $relative"
    }
}
foreach ($relative in $expectedListening) {
    $sourcePath = Join-Path $listeningRoot $relative
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        Fail "package is missing listening template: $relative"
    }
}

$issPath = Join-Path $repo '.github\scripts\windows11-listening-installer.iss'
Assert-File $issPath 'Inno Setup script'
$isccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
)
$iscc = $null
foreach ($candidate in $isccCandidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $iscc = $candidate
        break
    }
}
if ($null -eq $iscc) {
    $command = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        $iscc = $command.Source
    }
}
if ([string]::IsNullOrWhiteSpace($iscc) -or -not (Test-Path -LiteralPath $iscc -PathType Leaf)) {
    Fail 'Inno Setup 6 ISCC.exe was not found on the runner (no download is attempted)'
}

New-Item -ItemType Directory -Path $installerRoot -Force | Out-Null
Assert-Under $installerRoot $runnerTemp 'InstallerRoot after create'
$payload = Get-PayloadMap $packageRoot
if ($payload.count -le 0) {
    Fail 'package payload is empty'
}
$payloadDigest = Get-PayloadTreeDigest $payload.files

$compileArgs = @(
    "/DMyPackageDir=$packageRoot",
    "/DMyOutputDir=$installerRoot",
    "/DMyOutputBaseFilename=KGNext-Listening-Win11-x64-Setup",
    "/DMyAppVersion=$([string]$packageInfo.version)",
    "/DMyBuildId=$([string]$packageInfo.build_id)",
    $issPath
)
$compileLog = Join-Path $installerRoot 'installer-compile.log'
Invoke-External $iscc $compileArgs $compileLog

$installerPath = Join-Path $installerRoot $InstallerName
Assert-File $installerPath 'compiled installer'
$installerHash = Get-FileSha256 $installerPath
$installerBytes = (Get-Item -LiteralPath $installerPath).Length
$installerSignature = Get-AuthenticodeSignature -LiteralPath $installerPath -ErrorAction Stop
$installerSigned = ($installerSignature.Status -eq 'Valid')
if ($installerSigned) {
    Fail 'The test installer must remain unsigned'
}
if ([string]$installerSignature.Status -ne 'NotSigned') {
    Fail "Unexpected installer signature state: $($installerSignature.Status)"
}

$installDir = Join-Path $env:LOCALAPPDATA 'Programs\KindergartenManagerListeningTest'
$userRoot = Join-Path $env:LOCALAPPDATA 'KindergartenManagerListeningTest'
$dataRoot = Join-Path $userRoot 'data'
$credentialRoot = Join-Path $userRoot 'credentials'
if (Test-Path -LiteralPath $installDir) {
    Fail "Refuse pre-existing install directory: $installDir"
}
if (Test-Path -LiteralPath $userRoot) {
    Fail "Refuse pre-existing test data root: $userRoot"
}

$installProcess = Start-Process -FilePath $installerPath -ArgumentList @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-'
) -Wait -PassThru
if ($installProcess.ExitCode -ne 0) {
    Fail "Silent installer failed with exit code $($installProcess.ExitCode)"
}
Assert-Dir $installDir 'installed program directory'
Assert-File (Join-Path $installDir 'KGNext-E14.exe') 'installed main EXE'
if (-not (Test-Under $installDir (Join-Path $env:LOCALAPPDATA 'Programs'))) {
    Fail 'Installed program directory escaped LOCALAPPDATA\Programs'
}

$installedPayload = Get-PayloadMap $installDir -ExcludeUninstaller
if ($installedPayload.count -ne $payload.count) {
    Fail "Installed payload file count mismatch: $($installedPayload.count) != $($payload.count)"
}
foreach ($relative in $payload.files.Keys) {
    if (-not $installedPayload.files.ContainsKey($relative)) {
        Fail "Installed payload missing: $relative"
    }
    $expected = $payload.files[$relative]
    $actual = $installedPayload.files[$relative]
    if ([long]$expected.size -ne [long]$actual.size -or
        [string]$expected.sha256 -ne [string]$actual.sha256) {
        Fail "Installed payload mismatch: $relative"
    }
}

$programs = [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
$shortcutPath = Join-Path $programs (Join-Path $ShortcutFolder $ShortcutName)
Assert-File $shortcutPath 'Start Menu shortcut'
# Read the original Unicode link through the Shell property system. The
# legacy WScript reader can return empty fields for a localized link name.
$shell = New-Object -ComObject Shell.Application
$shortcutFolderItem = $shell.NameSpace([System.IO.Path]::GetDirectoryName($shortcutPath))
$shortcutItem = $shortcutFolderItem.ParseName($ShortcutName)
$shortcutTarget = [string]$shortcutItem.ExtendedProperty('System.Link.TargetParsingPath')
$shortcutArguments = [string]$shortcutItem.ExtendedProperty('System.Link.Arguments')
if ([string]::IsNullOrWhiteSpace($shortcutTarget) -or [string]::IsNullOrWhiteSpace($shortcutArguments)) {
    $probePath = Join-Path $installerRoot 'shortcut-probe.lnk'
    Copy-Item -LiteralPath $shortcutPath -Destination $probePath
    $wsh = New-Object -ComObject WScript.Shell
    $probeLink = $wsh.CreateShortcut($probePath)
    $shortcutTarget = [string]$probeLink.TargetPath
    $shortcutArguments = [string]$probeLink.Arguments
}
if ([string]::IsNullOrWhiteSpace($shortcutTarget)) {
    Fail 'Start Menu shortcut target could not be read'
}
$expectedTarget = [System.IO.Path]::GetFullPath((Join-Path $installDir 'KGNext-E14.exe'))
$actualTarget = [System.IO.Path]::GetFullPath($shortcutTarget)
if (-not $actualTarget.Equals($expectedTarget, [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail "Shortcut target mismatch: $actualTarget != $expectedTarget"
}
$expectedArguments = '--data "{0}" --credential-root "{1}"' -f $dataRoot, $credentialRoot
if (-not [string]::Equals(
    $shortcutArguments,
    $expectedArguments,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    Fail "Shortcut arguments mismatch: $shortcutArguments"
}

New-Item -ItemType Directory -Path $dataRoot, $credentialRoot -Force | Out-Null
$dataMarker = Join-Path $dataRoot 'synthetic-keep.kgmbackup'
$credentialMarker = Join-Path $credentialRoot 'synthetic-credential.marker'
[System.IO.File]::WriteAllText($dataMarker, 'synthetic listening data keep', [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText($credentialMarker, 'synthetic credential keep', [System.Text.UTF8Encoding]::new($false))
$dataHash = Get-FileSha256 $dataMarker
$credentialHash = Get-FileSha256 $credentialMarker

$uninstaller = Join-Path $installDir 'unins000.exe'
Assert-File $uninstaller 'Inno uninstaller'
$uninstallProcess = Start-Process -FilePath $uninstaller -ArgumentList @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
) -Wait -PassThru
if ($uninstallProcess.ExitCode -ne 0) {
    Fail "Silent uninstaller failed with exit code $($uninstallProcess.ExitCode)"
}
if (Test-Path -LiteralPath (Join-Path $installDir 'KGNext-E14.exe')) {
    Fail 'Uninstaller left the application EXE behind'
}
if (Test-Path -LiteralPath $shortcutPath) {
    Fail 'Uninstaller left the Start Menu shortcut behind'
}
if (-not (Test-Path -LiteralPath $dataMarker -PathType Leaf) -or
    (Get-FileSha256 $dataMarker) -ne $dataHash) {
    Fail 'Synthetic data archive was not preserved by uninstall'
}
if (-not (Test-Path -LiteralPath $credentialMarker -PathType Leaf) -or
    (Get-FileSha256 $credentialMarker) -ne $credentialHash) {
    Fail 'Synthetic credential marker was not preserved by uninstall'
}
if ((Get-FileSha256 $installerPath) -ne $installerHash) {
    Fail 'Installer bytes changed during the install/uninstall check'
}

$identity = [ordered]@{
    schema_version = 1
    repository = $Repository
    commit = $commit
    tree = $tree
    build_root_name = $buildLeaf
    build_id = [string]$packageInfo.build_id
    database_revision = $ExpectedRevision
    source = [ordered]@{
        freeze_digest = [string]$summary.build.source_freeze_digest
        freeze_stable = [bool]$summary.build.source_freeze_stable
        validation_summary_sha256 = $summaryHash
    }
    static_validation = [ordered]@{
        package = [ordered]@{
            ok = [bool]$summary.static_validation.package.ok
            checks = [int]$summary.static_validation.package.checks
            passed = [int]$summary.static_validation.package.passed
        }
        archive = [ordered]@{
            ok = [bool]$summary.static_validation.archive.ok
            checks = [int]$summary.static_validation.archive.checks
            passed = [int]$summary.static_validation.archive.passed
        }
    }
    installer = [ordered]@{
        name = $InstallerName
        sha256 = $installerHash
        bytes = [long]$installerBytes
        signed = [bool]$installerSigned
        authenticode_status = [string]$installerSignature.Status
        signed_uninstaller = $false
    }
    payload = [ordered]@{
        file_count = [int]$payload.count
        bytes = [long]$payload.bytes
        tree_sha256 = $payloadDigest
    }
    install_verification = [ordered]@{
        silent_install = $true
        silent_uninstall = $true
        payload_size_and_sha_matched = $true
        shortcut_path = $shortcutPath
        shortcut_target = $actualTarget
        shortcut_arguments = $expectedArguments
        data_preserved_after_uninstall = $true
    }
    scope = [ordered]@{
        runner = 'windows-2022-x64'
        target = 'Windows 11 x64 per-user unsigned test installer'
        install_dir = $installDir
        data_root = $dataRoot
        credential_root = $credentialRoot
        auto_launch_after_install = $false
        webview2_downloaded = $false
        data_migration = $false
        data_removed_on_uninstall = $false
        runtime_claim = 'Installer compile, silent install/uninstall and installed payload checks on GitHub windows-2022 only; not Windows 11, target-machine, teacher, Word or real-AI acceptance.'
    }
    source_scripts = [ordered]@{
        builder_sha256 = Get-FileSha256 (Join-Path $repo '.github\scripts\build-windows11-listening-installer.ps1')
        inno_sha256 = Get-FileSha256 $issPath
    }
}
$identityPath = Join-Path $installerRoot $IdentityName
$identityJson = $identity | ConvertTo-Json -Depth 12
[System.IO.File]::WriteAllText(
    $identityPath,
    $identityJson,
    [System.Text.UTF8Encoding]::new($false)
)

$identityHash = Get-FileSha256 $identityPath
$sumsText = (
    "$installerHash  $InstallerName`n" +
    "$identityHash  $IdentityName`n"
)
[System.IO.File]::WriteAllText(
    (Join-Path $installerRoot $SumsName),
    $sumsText,
    [System.Text.UTF8Encoding]::new($false)
)

$stepSummary = $env:GITHUB_STEP_SUMMARY
if (-not [string]::IsNullOrWhiteSpace($stepSummary)) {
    $markdown = @"
## Unsigned one-to-one-listening test installer

- Commit: ``$commit``
- Tree: ``$tree``
- Build ID: ``$($packageInfo.build_id)``
- Database revision: ``$ExpectedRevision``
- Installer: ``$InstallerName``, $installerBytes bytes, SHA-256 ``$installerHash``
- Signed: false (Authenticode ``$($installerSignature.Status)``)
- Payload: $($payload.count) files, $($payload.bytes) bytes
- Silent install/uninstall and payload SHA match: passed
- Start Menu shortcut target/arguments: passed
- Synthetic data/credential tree preserved after uninstall: passed
- Scope: GitHub windows-2022 installer and install/uninstall verification only; not Windows 11 runtime or teacher acceptance.

"@
    Add-Content -LiteralPath $stepSummary -Value $markdown -Encoding utf8
}

Write-Host "Installer: $installerPath"
Write-Host "Installer SHA-256: $installerHash"
Write-Host "Installer bytes: $installerBytes"
Write-Host "Identity: $identityPath"
Write-Host "Payload: $($payload.count) files / $($payload.bytes) bytes"
