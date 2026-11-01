<#
Build and statically verify the complete weekly Windows package on a fresh
GitHub windows-2022 x64 runner.  This script never launches the packaged app,
a helper, a server, the updater, or any target executable.  It is not a
Windows 11 runtime/target validation.

Only the minimal handoff is placed under EvidenceRoot\handoff.  Raw freeze,
full static reports, logs and source paths stay under EvidenceRoot\private and
are never uploaded by the workflow.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$EvidenceRoot,
    [Parameter(Mandatory = $true)][string]$RunId,
    [Parameter(Mandatory = $true)][string]$RunAttempt,
    [string]$Repository = $env:GITHUB_REPOSITORY,
    [string]$CommitSha = $env:GITHUB_SHA,
    [string]$ServerUrl = $env:GITHUB_SERVER_URL
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

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

if ($RunId -notmatch '^[0-9]+$' -or $RunAttempt -notmatch '^[0-9]+$') {
    Fail 'RunId and RunAttempt must be numeric'
}
if ($env:GITHUB_ACTIONS -ne 'true') {
    Fail 'This build script is restricted to ephemeral GitHub Actions runners'
}
if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    Fail 'RUNNER_TEMP is required'
}

$repo = [System.IO.Path]::GetFullPath($RepoRoot)
$runnerTemp = [System.IO.Path]::GetFullPath($env:RUNNER_TEMP)
$evidence = [System.IO.Path]::GetFullPath($EvidenceRoot)
$runnerPrefix = $runnerTemp.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
if (-not $evidence.StartsWith($runnerPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail "EvidenceRoot must be inside RUNNER_TEMP: $evidence"
}
if (Test-Path -LiteralPath $evidence) {
    Fail "EvidenceRoot must be fresh: $evidence"
}

Assert-File (Join-Path $repo 'desktop\build_e14.py') 'E14 builder'
Assert-File (Join-Path $repo 'desktop\verify_e14_package.py') 'package static verifier'
Assert-File (Join-Path $repo 'desktop\verify_e14_portable_archive.py') 'archive static verifier'
Assert-File (Join-Path $repo 'desktop\requirements-d1.lock.txt') 'locked Python requirements'
Assert-File (Join-Path $repo 'desktop\requirements-d1-build-constraints.txt') 'build constraints'
Assert-File (Join-Path $repo 'frontend\package-lock.json') 'frontend lockfile'
Assert-File (Join-Path $repo 'desktop\check_windows11_target.ps1') 'target preflight script'

$privateRoot = Join-Path $evidence 'private'
$reportsRoot = Join-Path $evidence 'reports'
$handoffRoot = Join-Path $evidence 'handoff'
New-Item -ItemType Directory -Path $privateRoot, $reportsRoot, $handoffRoot -Force | Out-Null

$pythonVersion = (& python --version 2>&1 | Out-String).Trim()
$nodeVersion = (& node --version 2>&1 | Out-String).Trim()
$npmVersion = (& npm --version 2>&1 | Out-String).Trim()
if ($pythonVersion -ne 'Python 3.14.10') {
    Fail "Expected Python 3.14.10, got: $pythonVersion"
}
& python -c "import struct, sys, sysconfig; assert sys.implementation.name == 'cpython'; assert sys.version_info[:3] == (3, 14, 10); assert struct.calcsize('P') * 8 == 64; assert sysconfig.get_platform().lower() == 'win-amd64'; assert getattr(sys, '_is_gil_enabled', lambda: True)()"
if ($LASTEXITCODE -ne 0) {
    Fail 'Python is not the required CPython 3.14.10 x64 standard-GIL build'
}
if ($nodeVersion -ne 'v26.12.1') {
    Fail "Expected Node v26.12.1, got: $nodeVersion"
}
$commit = (& git -C $repo rev-parse HEAD 2>&1 | Out-String).Trim()
if ($commit -notmatch '^[0-9a-f]{40}$') {
    Fail "Could not resolve commit: $commit"
}
if (-not [string]::IsNullOrWhiteSpace($CommitSha) -and $CommitSha -ne $commit) {
    Fail "GITHUB_SHA does not match checkout HEAD: $CommitSha != $commit"
}

$workflowRel = '.github/workflows/windows11-weekly-validation.yml'
$scriptRel = '.github/scripts/build-windows11-validation.ps1'
$workflowPath = Join-Path $repo $workflowRel
$scriptPath = Join-Path $repo $scriptRel
Assert-File $workflowPath 'CI workflow'
Assert-File $scriptPath 'CI build script'
$workflowBlob = (& git -C $repo rev-parse "HEAD:$workflowRel" 2>&1 | Out-String).Trim()
$scriptBlob = (& git -C $repo rev-parse "HEAD:$scriptRel" 2>&1 | Out-String).Trim()
$tree = (& git -C $repo rev-parse 'HEAD^{tree}' 2>&1 | Out-String).Trim()
if ($workflowBlob -notmatch '^[0-9a-f]{40}$' -or $scriptBlob -notmatch '^[0-9a-f]{40}$' -or $tree -notmatch '^[0-9a-f]{40}$') {
    Fail 'Could not resolve committed Git blob/tree identity for the CI entry files'
}
$workflowBefore = (Get-FileHash -LiteralPath $workflowPath -Algorithm SHA256).Hash.ToLowerInvariant()
$scriptBefore = (Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant()
$trackedCleanBefore = ((& git -C $repo status --porcelain=v1 --untracked-files=no 2>&1 | Out-String).Trim())
if (-not [string]::IsNullOrEmpty($trackedCleanBefore)) {
    Fail "Tracked checkout is not clean before build: $trackedCleanBefore"
}

$buildRootName = "desktop-e14-weekly-ci-$RunId-$RunAttempt"
$buildRoot = Join-Path $repo ("build\" + $buildRootName)
if (Test-Path -LiteralPath $buildRoot) {
    Fail "Build root must be fresh: $buildRoot"
}
$frontendRoot = Join-Path $repo 'frontend'
$venvRoot = Join-Path $repo 'desktop\.venv-d1'
if (Test-Path -LiteralPath $venvRoot) {
    Fail "Refuse existing local venv: $venvRoot"
}

$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
$pipLog = Join-Path $privateRoot 'pip-install.log'
$npmLog = Join-Path $privateRoot 'npm-ci.log'
$buildLog = Join-Path $privateRoot 'build.log'
$hashOut = Join-Path $privateRoot 'package-files.json'
$freezeOut = Join-Path $privateRoot 'source-freeze.json'

& python -m venv $venvRoot 2>&1 | Tee-Object -FilePath (Join-Path $privateRoot 'venv-create.log')
if ($LASTEXITCODE -ne 0) { Fail 'python -m venv failed' }
Assert-File $venvPython 'venv Python'

$pipVersion = (& $venvPython -m pip --version 2>&1 | Out-String).Trim()
$pipHelp = (& $venvPython -m pip install --help 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $pipHelp -notmatch '--build-constraint') {
    Fail 'Bundled pip does not support explicit --build-constraint'
}

$lock = Join-Path $repo 'desktop\requirements-d1.lock.txt'
$constraints = Join-Path $repo 'desktop\requirements-d1-build-constraints.txt'
$env:PIP_NO_INPUT = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
$pipArgs = @(
    '-m', 'pip', 'install',
    '--require-hashes', '--no-deps',
    '--requirement', $lock,
    '--build-constraint', $constraints
)
Invoke-External $venvPython $pipArgs $pipLog

Push-Location $frontendRoot
try {
    Invoke-External 'npm' @('ci', '--no-audit', '--no-fund') $npmLog
} finally {
    Pop-Location
}

$portableDir = Join-Path $buildRoot 'dist'
$buildArgs = @(
    'desktop\build_e14.py',
    '--build-root', $buildRoot,
    '--portable-dir', $portableDir,
    '--hash-out', $hashOut,
    '--source-freeze-out', $freezeOut
)
Push-Location $repo
try {
    Invoke-External $venvPython $buildArgs $buildLog
} finally {
    Pop-Location
}

$packageRoot = Join-Path $buildRoot 'package\KGNext-E14'
$archiveName = 'KGNext-E14-win11-r01.zip'
$archivePath = Join-Path $portableDir $archiveName
Assert-Dir $packageRoot 'built package root'
Assert-File $archivePath 'built product ZIP'
Assert-File (Join-Path $packageRoot 'package-info.json') 'package-info.json'
Assert-File (Join-Path $packageRoot 'KGNext-E14.exe') 'main EXE'
Assert-File $hashOut 'package hash report'
Assert-File $freezeOut 'source freeze report'

$freeze = Get-Content -LiteralPath $freezeOut -Raw -Encoding utf8 | ConvertFrom-Json
$hashData = Get-Content -LiteralPath $hashOut -Raw -Encoding utf8 | ConvertFrom-Json
$packageInfo = Get-Content -LiteralPath (Join-Path $packageRoot 'package-info.json') -Raw -Encoding utf8 | ConvertFrom-Json
if (-not [bool]$freeze.stable) { Fail 'source freeze is not stable' }
if ([string]$freeze.before.digest -ne [string]$freeze.after.digest) {
    Fail 'source freeze before/after digest mismatch'
}
if ([string]$hashData.source_freeze_digest -ne [string]$freeze.before.digest) {
    Fail 'hash report freeze digest mismatch'
}
if ([string]$packageInfo.build_id -ne [string]$hashData.build_id) {
    Fail 'package-info build_id mismatch'
}
if ([string]$packageInfo.database_revision -ne [string]$freeze.database_revision) {
    Fail 'package-info database revision mismatch'
}
if ([string]$packageInfo.source_commit -ne $commit) {
    Fail 'package-info source commit mismatch'
}

$portableManifestPath = Join-Path $portableDir 'package-files.json'
$portableSumsPath = Join-Path $portableDir 'SHA256SUMS.txt'
$buildIdentityPath = Join-Path $packageRoot '_internal\build_identity.json'
$frontendPath = Join-Path $buildRoot 'frontend'
Assert-File $portableManifestPath 'portable package manifest'
Assert-File $portableSumsPath 'portable SHA256SUMS'
Assert-File $buildIdentityPath 'build_identity.json'
Assert-Dir $frontendPath 'built frontend output'
$portableManifest = Get-Content -LiteralPath $portableManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
$buildIdentity = Get-Content -LiteralPath $buildIdentityPath -Raw -Encoding utf8 | ConvertFrom-Json
$actualFrontendCount = @(
    Get-ChildItem -LiteralPath $frontendPath -Recurse -File -ErrorAction Stop
).Count
if ($actualFrontendCount -le 0) { Fail 'built frontend output contains no files' }

foreach ($freezeCommit in @([string]$freeze.commit, [string]$freeze.before.commit, [string]$freeze.after.commit)) {
    if ($freezeCommit -ne $commit) { Fail 'source freeze commit mismatch with checkout' }
}
if ([string]$freeze.build_id -ne [string]$packageInfo.build_id) {
    Fail 'source freeze build_id mismatch with package-info'
}
if ([string]$freeze.build_id -ne [string]$hashData.build_id) {
    Fail 'source freeze build_id mismatch with hash report'
}
if ([string]$buildIdentity.build_id -ne [string]$packageInfo.build_id) {
    Fail 'build_identity build_id mismatch with package-info'
}
if ([string]$portableManifest.build_id -ne [string]$packageInfo.build_id) {
    Fail 'portable manifest build_id mismatch with package-info'
}
if ([string]$buildIdentity.database_revision -ne [string]$packageInfo.database_revision) {
    Fail 'build_identity database revision mismatch'
}
if ([string]$portableManifest.database_revision -ne [string]$packageInfo.database_revision) {
    Fail 'portable manifest database revision mismatch'
}
if ([string]$buildIdentity.python -ne '3.14.10') {
    Fail 'build_identity Python version mismatch'
}
if ([string]$buildIdentity.platform -ne 'windows' -or [string]$buildIdentity.arch -ne 'x64') {
    Fail 'build_identity platform/arch mismatch'
}
if ([string]$portableManifest.source_freeze_digest -ne [string]$freeze.before.digest) {
    Fail 'portable manifest freeze digest mismatch'
}
if ((Get-FileHash -LiteralPath $portableManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$hashData.manifest_sha256) {
    Fail 'portable manifest SHA-256 mismatch with hash report'
}
if ((Get-FileHash -LiteralPath $portableSumsPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$hashData.sums_sha256) {
    Fail 'portable SHA256SUMS SHA-256 mismatch with hash report'
}
if ([int]$packageInfo.frontend_file_count -ne $actualFrontendCount) {
    Fail 'package-info frontend file count mismatch with actual frontend output'
}
if ([int]$freeze.frontend_file_count -ne $actualFrontendCount) {
    Fail 'source freeze frontend file count mismatch with actual frontend output'
}
if ([int]$hashData.frontend_file_count -ne $actualFrontendCount) {
    Fail 'hash report frontend file count mismatch with actual frontend output'
}
if ([string]$packageInfo.frontend_digest -ne [string]$freeze.frontend_output_digest) {
    Fail 'package-info/freeze frontend digest mismatch'
}
if ([string]$packageInfo.frontend_digest -ne [string]$hashData.frontend_digest) {
    Fail 'package-info/hash-report frontend digest mismatch'
}

$guardCode = @'
import json, os, runpy, sys
ATTEMPT_PATH = sys.argv[1]
VERIFIER = sys.argv[2]
DENY = {
    "subprocess.Popen", "os.system", "os.startfile",
    "os.fork", "os.forkpty", "os.posix_spawn",
}
ATTEMPTS = []

def _write_attempts():
    payload = {
        "schema_version": 1,
        "guard_marker": "kgm-ci-static-source-guard-v1",
        "verifier": os.path.basename(VERIFIER),
        "attempts": ATTEMPTS,
        "completed": True,
    }
    temporary = ATTEMPT_PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, ATTEMPT_PATH)

def _guard(event, args):
    if event in DENY or event.startswith("os.exec") or event.startswith("os.spawn") or event.startswith("socket."):
        ATTEMPTS.append({"event": event})
        _write_attempts()
        raise RuntimeError("B3_STATIC_SOURCE_GUARD_DENIED:" + event)

sys.addaudithook(_guard)
sys.path.insert(0, os.path.dirname(os.path.abspath(VERIFIER)))
try:
    sys.argv = [VERIFIER] + sys.argv[3:]
    runpy.run_path(VERIFIER, run_name="__main__")
finally:
    _write_attempts()
'@
$guardHash = [System.BitConverter]::ToString(
    [System.Security.Cryptography.SHA256]::Create().ComputeHash(
        ([System.Text.UTF8Encoding]::new($false)).GetBytes($guardCode)
    )
).Replace('-', '').ToLowerInvariant()
$guardReport = [ordered]@{
    schema_version = 1
    installed_before_import = $true
    verifier_parent_on_sys_path = $true
    guard_code_sha256 = $guardHash
    denied_events = @(
        'subprocess.Popen', 'os.system', 'os.startfile',
        'os.exec*', 'os.spawn*', 'os.fork', 'os.forkpty', 'os.posix_spawn',
        'socket.*'
    )
    attempt_reports = @()
    attempts = 0
    completed = $false
    scope = 'Python audit hook for static verifier imports; not OS packet capture, WebView2, or target network proof.'
}
$guardReportPath = Join-Path $reportsRoot 'source-audit-guard.json'

function Read-GuardAttempts {
    param([string]$Path, [string]$VerifierName)
    Assert-File $Path 'guarded verifier attempt report'
    $report = Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json
    $schemaProperty = $report.PSObject.Properties['schema_version']
    if ($null -eq $schemaProperty -or $schemaProperty.Value -ne 1) {
        Fail 'guarded verifier attempt report schema mismatch'
    }
    $markerProperty = $report.PSObject.Properties['guard_marker']
    if ($null -eq $markerProperty -or [string]$markerProperty.Value -ne 'kgm-ci-static-source-guard-v1') {
        Fail 'guarded verifier attempt report marker mismatch'
    }
    if ([string]$report.verifier -ne $VerifierName) {
        Fail 'guarded verifier attempt report verifier mismatch'
    }
    $completedProperty = $report.PSObject.Properties['completed']
    if ($null -eq $completedProperty -or $completedProperty.Value -isnot [bool] -or -not $completedProperty.Value) {
        Fail 'guarded verifier attempt report is incomplete'
    }
    $attemptsProperty = $report.PSObject.Properties['attempts']
    if ($null -eq $attemptsProperty) {
        Fail 'guarded verifier attempt report has no attempts array'
    }
    if ($null -ne $attemptsProperty.Value -and $attemptsProperty.Value -isnot [System.Array]) {
        Fail 'guarded verifier attempts is not an array'
    }
    $attempts = @($attemptsProperty.Value)
    if ($attempts.Count -ne 0) {
        Fail "guarded verifier blocked process/socket attempts: $($attempts.Count)"
    }
    return [pscustomobject]@{
        verifier = $VerifierName
        attempts = $attempts.Count
        completed = $true
    }
}

function Invoke-GuardedVerifier {
    param(
        [string]$Verifier,
        [string[]]$VerifierArguments,
        [string]$LogPath,
        [string]$AttemptPath
    )
    $callArgs = @('-c', $guardCode, $AttemptPath, $Verifier) + $VerifierArguments
    Invoke-External $venvPython $callArgs $LogPath
    $attempt = Read-GuardAttempts $AttemptPath ([System.IO.Path]::GetFileName($Verifier))
    $guardReport.attempt_reports += [ordered]@{
        verifier = $attempt.verifier
        attempts = $attempt.attempts
        completed = $attempt.completed
    }
    $guardReport.attempts = [int]$guardReport.attempts + $attempt.attempts
}

function Read-StaticReport {
    param([string]$Path, [string]$Label)
    Assert-File $Path "$Label static report"
    $report = Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json
    $okProperty = $report.PSObject.Properties['ok']
    if ($null -eq $okProperty -or $okProperty.Value -isnot [bool] -or -not $okProperty.Value) {
        Fail "$Label static verification did not pass"
    }
    $modeProperty = $report.PSObject.Properties['mode']
    if ($null -eq $modeProperty -or [string]$modeProperty.Value -ne 'static') {
        Fail "$Label static report mode is not explicit static"
    }
    foreach ($name in @('missing_checks', 'non_bool_checks', 'unknown_checks', 'failed_checks')) {
        $property = $report.PSObject.Properties[$name]
        if ($null -eq $property) {
            Fail "$Label static report is missing $name"
        }
        if ($null -ne $property.Value -and $property.Value -isnot [System.Array]) {
            Fail "$Label static report $name is not an array"
        }
        if (@($property.Value).Count -ne 0) {
            Fail "$Label static report has non-empty $name"
        }
    }
    $checksProperty = $report.PSObject.Properties['checks']
    if ($null -eq $checksProperty -or $checksProperty.Value -isnot [System.Management.Automation.PSCustomObject]) {
        Fail "$Label static report has no checks object"
    }
    $checkProperties = @($checksProperty.Value.PSObject.Properties)
    if ($checkProperties.Count -le 0) {
        Fail "$Label static report has no checks"
    }
    foreach ($check in $checkProperties) {
        if ($check.Value -isnot [bool] -or $check.Value -ne $true) {
            Fail "$Label check is not explicit true: $($check.Name)"
        }
    }
    return [pscustomobject]@{
        ok = $true
        checks = $checkProperties.Count
        passed = $checkProperties.Count
        mode = 'static'
    }
}

$packageReportPath = Join-Path $reportsRoot 'package-static.json'
$packageLog = Join-Path $privateRoot 'package-static.log'
$packageArgs = @(
    '--mode', 'static',
    '--package', $packageRoot,
    '--source-freeze', $freezeOut,
    '--frontend-build', (Join-Path $buildRoot 'frontend'),
    '--out', $packageReportPath
)
Invoke-GuardedVerifier (Join-Path $repo 'desktop\verify_e14_package.py') $packageArgs $packageLog (Join-Path $reportsRoot 'guard-package-attempts.json')
$packageStatic = Read-StaticReport $packageReportPath 'package'

$archiveReportPath = Join-Path $reportsRoot 'archive-static.json'
$archiveLog = Join-Path $privateRoot 'archive-static.log'
$archiveArgs = @(
    '--archive', $archivePath,
    '--package', $packageRoot,
    '--source-freeze', $freezeOut,
    '--out', $archiveReportPath
)
Invoke-GuardedVerifier (Join-Path $repo 'desktop\verify_e14_portable_archive.py') $archiveArgs $archiveLog (Join-Path $reportsRoot 'guard-archive-attempts.json')
$archiveStatic = Read-StaticReport $archiveReportPath 'archive'
$guardReport.completed = $true
if ([int]$guardReport.attempts -ne 0) {
    Fail 'guarded verifier attempt report contains blocked events'
}
$guardReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $guardReportPath -Encoding utf8

$workflowAfter = (Get-FileHash -LiteralPath $workflowPath -Algorithm SHA256).Hash.ToLowerInvariant()
$scriptAfter = (Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant()
$trackedCleanAfter = ((& git -C $repo status --porcelain=v1 --untracked-files=no 2>&1 | Out-String).Trim())
if (-not [string]::IsNullOrEmpty($trackedCleanAfter)) {
    Fail "Tracked checkout changed during build: $trackedCleanAfter"
}
$ciSourceStable = (
    $workflowBefore -eq $workflowAfter -and
    $scriptBefore -eq $scriptAfter -and
    [string]::IsNullOrEmpty($trackedCleanBefore) -and
    [string]::IsNullOrEmpty($trackedCleanAfter)
)
if (-not $ciSourceStable) {
    Fail 'CI entry workflow/script source identity is not stable'
}
$ciSource = [ordered]@{
    schema_version = 1
    commit = $commit
    tree = $tree
    tracked_clean_before = [string]::IsNullOrEmpty($trackedCleanBefore)
    tracked_clean_after = [string]::IsNullOrEmpty($trackedCleanAfter)
    workflow = [ordered]@{
        path = $workflowRel
        blob = $workflowBlob
        sha256_before = $workflowBefore
        sha256_after = $workflowAfter
        stable = ($workflowBefore -eq $workflowAfter)
    }
    script = [ordered]@{
        path = $scriptRel
        blob = $scriptBlob
        sha256_before = $scriptBefore
        sha256_after = $scriptAfter
        stable = ($scriptBefore -eq $scriptAfter)
    }
    stable = $ciSourceStable
}

$zipHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$zipBytes = (Get-Item -LiteralPath $archivePath).Length
if ([string]$hashData.archive_sha256 -ne $zipHash) { Fail 'ZIP SHA-256 mismatch with build report' }
if ([long]$hashData.archive_bytes -ne [long]$zipBytes) { Fail 'ZIP byte size mismatch with build report' }

$peFiles = @(
    Get-ChildItem -LiteralPath $packageRoot -Recurse -File -ErrorAction Stop |
        Where-Object { $_.Extension.ToLowerInvariant() -in @('.exe', '.dll', '.pyd') }
)
$statusCounts = [ordered]@{}
foreach ($pe in $peFiles) {
    try {
        $signature = Get-AuthenticodeSignature -LiteralPath $pe.FullName -ErrorAction Stop
        $status = [string]$signature.Status
    } catch {
        $status = 'ReadError'
    }
    if (-not $statusCounts.Contains($status)) { $statusCounts[$status] = 0 }
    $statusCounts[$status] = [int]$statusCounts[$status] + 1
}
$mainExe = Join-Path $packageRoot 'KGNext-E14.exe'
$mainSignature = Get-AuthenticodeSignature -LiteralPath $mainExe -ErrorAction Stop
$signatureSummary = [ordered]@{
    checked_pe_files = [int]$peFiles.Count
    status_counts = $statusCounts
    main_exe_status = [string]$mainSignature.Status
    read_only = $true
    signed_by_ci = $false
    policy_changed = $false
}

$targetScript = Join-Path $repo 'desktop\check_windows11_target.ps1'
$targetScriptName = 'check_windows11_target.ps1'
$targetScriptHash = (Get-FileHash -LiteralPath $targetScript -Algorithm SHA256).Hash.ToLowerInvariant()
$handoffTargetScript = Join-Path $handoffRoot $targetScriptName
Copy-Item -LiteralPath $targetScript -Destination $handoffTargetScript
if ((Get-FileHash -LiteralPath $handoffTargetScript -Algorithm SHA256).Hash.ToLowerInvariant() -ne $targetScriptHash) {
    Fail 'target script copy is not byte-identical'
}

$manualSource = Join-Path $repo 'docs\bootstrap\desktop-weekly-windows11-manual.md'
$manualName = 'desktop-weekly-windows11-manual.md'
Assert-File $manualSource 'target manual'
$manualIncluded = $true
$manualHash = (Get-FileHash -LiteralPath $manualSource -Algorithm SHA256).Hash.ToLowerInvariant()
Copy-Item -LiteralPath $manualSource -Destination (Join-Path $handoffRoot $manualName)
if ((Get-FileHash -LiteralPath (Join-Path $handoffRoot $manualName) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manualHash) {
    Fail 'manual copy hash mismatch'
}

$handoffZip = Join-Path $handoffRoot $archiveName
Copy-Item -LiteralPath $archivePath -Destination $handoffZip
if ((Get-FileHash -LiteralPath $handoffZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $zipHash) {
    Fail 'handoff ZIP copy hash mismatch'
}
if ((Get-Item -LiteralPath $handoffZip).Length -ne $zipBytes) {
    Fail 'handoff ZIP copy byte size mismatch'
}

$sumLines = New-Object System.Collections.Generic.List[string]
$sumLines.Add("$zipHash  $archiveName")
$sumLines.Add("$targetScriptHash  $targetScriptName")
$sumLines.Add("$manualHash  $manualName")
$sumText = ($sumLines -join "`n") + "`n"
[System.IO.File]::WriteAllText(
    (Join-Path $handoffRoot 'SHA256SUMS.txt'),
    $sumText,
    [System.Text.UTF8Encoding]::new($false)
)

$artifactName = "windows11-weekly-validation-$commit-$RunId-$RunAttempt"
$summary = [ordered]@{
    schema_version = 1
    repository = $Repository
    commit = $commit
    run_id = $RunId
    run_attempt = $RunAttempt
    workflow = 'windows11-weekly-validation'
    runner = 'windows-2022-x64'
    tree = $tree
    runtime_claim = 'GitHub windows-2022 x64 build and static verification only; not Windows 11 runtime, target-machine, teacher, Word, or real-AI acceptance.'
    toolchain = [ordered]@{
        python = $pythonVersion
        pip = $pipVersion
        node = $nodeVersion
        npm = $npmVersion
    }
    ci_source = $ciSource
    build = [ordered]@{
        build_root_name = $buildRootName
        build_id = [string]$packageInfo.build_id
        database_revision = [string]$packageInfo.database_revision
        source_freeze_digest = [string]$freeze.before.digest
        source_freeze_stable = [bool]$freeze.stable
        source_freeze_file_count = @($freeze.before.files).Count
        frontend_output_digest = [string]$freeze.frontend_output_digest
        frontend_file_count = [int]$freeze.frontend_file_count
    }
    product_zip = [ordered]@{
        name = $archiveName
        sha256 = $zipHash
        bytes = [long]$zipBytes
    }
    target_script = [ordered]@{
        name = $targetScriptName
        sha256 = $targetScriptHash
    }
    manual = [ordered]@{
        included = [bool]$manualIncluded
        name = $manualName
        sha256 = $manualHash
    }
    static_validation = [ordered]@{
        package = [ordered]@{
            mode = $packageStatic.mode
            ok = $packageStatic.ok
            checks = $packageStatic.checks
            passed = $packageStatic.passed
        }
        archive = [ordered]@{
            mode = $archiveStatic.mode
            ok = $archiveStatic.ok
            checks = $archiveStatic.checks
            passed = $archiveStatic.passed
        }
        source_audit_guard = $guardReport
    }
    signatures = $signatureSummary
    artifact = [ordered]@{
        wrapper_name = $artifactName
        download_hint = 'Download the workflow artifact; the internal product ZIP keeps the current basename.'
    }
}
$summaryPath = Join-Path $handoffRoot 'validation-summary.json'
$summaryJson = $summary | ConvertTo-Json -Depth 12
[System.IO.File]::WriteAllText(
    $summaryPath,
    $summaryJson,
    [System.Text.UTF8Encoding]::new($false)
)
if (-not (Test-Path -LiteralPath $summaryPath -PathType Leaf)) {
    Fail 'validation summary was not written'
}

$stepSummary = $env:GITHUB_STEP_SUMMARY
if (-not [string]::IsNullOrWhiteSpace($stepSummary)) {
    $markdown = @"
## Windows 11 weekly package build

- Repository: ``$Repository``
- Run: ``$RunId`` attempt ``$RunAttempt``
- Commit: ``$commit``
- Tree: ``$tree``
- Build ID: ``$($packageInfo.build_id)``
- Database revision: ``$($packageInfo.database_revision)``
- Python: ``$pythonVersion`` (pip ``$pipVersion``)
- Node: ``$nodeVersion`` (npm ``$npmVersion``)
- CI source stable: $ciSourceStable (workflow/script raw hashes)
- Product ZIP: ``$archiveName``, $zipBytes bytes, SHA-256 ``$zipHash``
- Target script SHA-256: ``$targetScriptHash``
- Manual: ``$manualName``, SHA-256 ``$manualHash``
- Source freeze: ``$($freeze.before.digest)`` (stable: $($freeze.stable))
- Static checks: package $($packageStatic.passed)/$($packageStatic.checks), archive $($archiveStatic.passed)/$($archiveStatic.checks)
- Guard attempts: $($guardReport.attempts) (Python audit hook; not OS network proof)
- PE signatures: $($peFiles.Count) files; main EXE status ``$($mainSignature.Status)``
- Artifact: ``$artifactName``
- Runtime claim: GitHub windows-2022 x64 build/static verification only; not Windows 11 runtime or teacher acceptance.

"@
    Add-Content -LiteralPath $stepSummary -Value $markdown -Encoding utf8
}

Write-Host "Handoff ready: $handoffRoot"
Write-Host "Product ZIP: $archiveName $zipHash $zipBytes bytes"
Write-Host "Build ID: $($packageInfo.build_id)"
Write-Host "Static checks: package=$($packageStatic.passed)/$($packageStatic.checks) archive=$($archiveStatic.passed)/$($archiveStatic.checks)"
