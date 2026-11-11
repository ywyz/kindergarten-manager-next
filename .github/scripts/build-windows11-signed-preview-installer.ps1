[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AppSource,
    [Parameter(Mandatory = $true)][string]$UpdaterSource,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [Parameter(Mandatory = $true)][string]$AppVersion,
    [Parameter(Mandatory = $true)][string]$BuildId,
    [string]$NumericVersion = '',
    [Parameter(Mandatory = $true)][string]$IsccPath,
    [string]$CertumSignCommand = '',
    [switch]$SyntaxCheck
)

$ErrorActionPreference = 'Stop'
$AppSource = [IO.Path]::GetFullPath($AppSource)
$UpdaterSource = [IO.Path]::GetFullPath($UpdaterSource)
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$IsccPath = [IO.Path]::GetFullPath($IsccPath)
$issPath = Join-Path $PSScriptRoot 'windows11-signed-preview-installer.iss'
$appExe = Join-Path $AppSource 'KindergartenManager.exe'
$updaterExe = Join-Path $UpdaterSource 'KindergartenManagerUpdater.exe'

function Assert-NoVisibleReparse([string]$Path, [string]$Label) {
    $current = [IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrEmpty($current)) {
        $item = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
        if ($null -ne $item -and (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw "$Label contains a visible reparse point: $current"
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ([string]::IsNullOrEmpty($parent) -or $parent -eq $current) { break }
        $current = $parent
    }
}

function Test-PathSameOrNested([string]$Left, [string]$Right) {
    $leftPath = [IO.Path]::GetFullPath($Left).TrimEnd('\') + '\'
    $rightPath = [IO.Path]::GetFullPath($Right).TrimEnd('\') + '\'
    return $leftPath.Equals($rightPath, [StringComparison]::OrdinalIgnoreCase) -or
        $leftPath.StartsWith($rightPath, [StringComparison]::OrdinalIgnoreCase) -or
        $rightPath.StartsWith($leftPath, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-DisjointPaths([string]$Left, [string]$Right, [string]$Label) {
    if (Test-PathSameOrNested $Left $Right) {
        throw "$Label must not overlap or contain one another: $Left ; $Right"
    }
}

function Assert-InputDirectory([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label is not a directory: $Path"
    }
}
function Get-VerifiedEntrySignature([string]$Path, [string]$Label) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate) {
        throw "$Label is not validly Authenticode-signed: $($signature.Status)"
    }
    if ($null -eq $signature.TimeStamperCertificate) {
        throw "$Label has no timestamp countersignature."
    }
    return $signature
}

function Assert-NoPrivateKeyMaterial($Value, [string]$Path) {
    if ($null -eq $Value) { return }
    if ($Value -is [string]) {
        if ($Value -match '-----BEGIN [A-Z ]*PRIVATE KEY-----') {
            throw "Private key material found in release config: $Path"
        }
        return
    }
    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        $index = 0
        foreach ($item in $Value) {
            Assert-NoPrivateKeyMaterial $item "$Path[$index]"
            $index += 1
        }
        return
    }
    if ($Value -is [pscustomobject]) {
        foreach ($property in $Value.PSObject.Properties) {
            if ($property.Name -match '(?i)(private[_-]?key|privatekey|pfx|p12|secret|password)') {
                throw "Private key material found in release config: $Path.$($property.Name)"
            }
            Assert-NoPrivateKeyMaterial $property.Value "$Path.$($property.Name)"
        }
    }
}

function Read-PublicReleaseConfig([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label release config is missing: $Path"
    }
    $raw = Get-Content -LiteralPath $Path -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "$Label release config is empty: $Path"
    }
    if ($raw -match '-----BEGIN [A-Z ]*PRIVATE KEY-----') {
        throw "$Label release config contains a private key: $Path"
    }
    try {
        $parsed = $raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "$Label release config is not valid JSON: $Path"
    }
    Assert-NoPrivateKeyMaterial $parsed $Label
    return [pscustomobject]@{
        path = $Path
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

Assert-InputDirectory $AppSource 'AppSource'
Assert-InputDirectory $UpdaterSource 'UpdaterSource'
if (-not (Test-Path -LiteralPath $appExe -PathType Leaf)) {
    throw "AppSource is missing the canonical KindergartenManager.exe: $appExe"
}
if (-not (Test-Path -LiteralPath $updaterExe -PathType Leaf)) {
    throw "UpdaterSource is missing KindergartenManagerUpdater.exe: $updaterExe"
}
if ($AppSource -eq $UpdaterSource) {
    throw 'AppSource and UpdaterSource must be distinct verified directories.'
}
Assert-NoVisibleReparse $AppSource 'AppSource'
Assert-NoVisibleReparse $UpdaterSource 'UpdaterSource'
if (Test-Path -LiteralPath $OutputDir) {
    throw "OutputDir must be a new, non-existing directory: $OutputDir"
}
Assert-NoVisibleReparse $OutputDir 'OutputDir'
Assert-DisjointPaths $OutputDir $AppSource 'OutputDir/AppSource'
Assert-DisjointPaths $OutputDir $UpdaterSource 'OutputDir/UpdaterSource'
if (-not (Test-Path -LiteralPath $IsccPath -PathType Leaf)) {
    throw "ISCC.exe not found: $IsccPath"
}
$isccSignature = Get-AuthenticodeSignature -LiteralPath $IsccPath
if ($isccSignature.Status -ne 'Valid' -or $null -eq $isccSignature.SignerCertificate) {
    throw "ISCC.exe is not validly Authenticode-signed: $($isccSignature.Status)"
}
$isccInfo = (Get-Item -LiteralPath $IsccPath).VersionInfo
if ($isccInfo.FileDescription -notlike '*Inno Setup*Command-Line Compiler*') {
    throw "Unexpected ISCC.exe description: $($isccInfo.FileDescription)"
}
if ($BuildId -notmatch '^[A-Za-z0-9._+-]{1,80}$') {
    throw 'BuildId must be 1..80 characters of A-Z a-z 0-9 . _ + -'
}
if ($AppVersion -notmatch '^[A-Za-z0-9._+-]{1,80}$') {
    throw 'AppVersion must be 1..80 characters of A-Z a-z 0-9 . _ + -'
}
if ([string]::IsNullOrWhiteSpace($NumericVersion)) {
    $match = [regex]::Match($AppVersion, '^(\d+)\.(\d+)\.(\d+)')
    if (-not $match.Success) {
        throw 'AppVersion must start with major.minor.patch when NumericVersion is omitted.'
    }
    $NumericVersion = "$($match.Groups[1].Value).$($match.Groups[2].Value).$($match.Groups[3].Value).0"
}
if ($NumericVersion -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    throw 'NumericVersion must be four numeric components (e.g. 0.1.0.0).'
}

# The installer inputs are release payloads only. A private key in either tree
# is a packaging error; signing is performed later by Codex with Certum.
foreach ($source in @($AppSource, $UpdaterSource)) {
    $keyFiles = @(Get-ChildItem -LiteralPath $source -Recurse -File -ErrorAction Stop |
        Where-Object { $_.Extension -in @('.pfx', '.p12', '.pem', '.key') })
    if ($keyFiles.Count -gt 0) {
        throw "Private-key material is not allowed in installer inputs: $($keyFiles[0].FullName)"
    }
}

if (-not (Test-Path -LiteralPath $issPath -PathType Leaf)) {
    throw "Installer script not found: $issPath"
}
$signedInputsOnly = $false
$appSignature = $null
$updaterSignature = $null
$appConfig = $null
$updaterConfig = $null
if ($SyntaxCheck) {
    if ($CertumSignCommand) {
        throw 'Do not combine -SyntaxCheck with -CertumSignCommand.'
    }
} else {
    if ([string]::IsNullOrWhiteSpace($CertumSignCommand)) {
        throw 'Signed build requires -CertumSignCommand; use -SyntaxCheck only for an unsigned placeholder.'
    }
    if (-not $CertumSignCommand.Contains('$f')) {
        throw 'CertumSignCommand must contain the Inno SignTool file placeholder $f.'
    }
    if ($CertumSignCommand -notmatch '(?i)/fd\s+sha256') {
        throw 'CertumSignCommand must include /fd sha256.'
    }
    if ($CertumSignCommand -notmatch '(?i)/tr\s+\S+' -or $CertumSignCommand -notmatch '(?i)/td\s+sha256') {
        throw 'CertumSignCommand must include RFC3161 /tr <url> and /td sha256.'
    }
    $appSignature = Get-VerifiedEntrySignature $appExe 'KindergartenManager.exe'
    $updaterSignature = Get-VerifiedEntrySignature $updaterExe 'KindergartenManagerUpdater.exe'
    $appConfig = Read-PublicReleaseConfig (Join-Path $AppSource '_internal\update_release.json') 'App'
    $updaterConfig = Read-PublicReleaseConfig (Join-Path $UpdaterSource 'update_release.json') 'Updater'
    if ($appConfig.sha256 -ne $updaterConfig.sha256) {
        throw 'App and updater update_release.json must have identical content.'
    }
    $signedInputsOnly = $true
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$isccArgs = @(
    "/DAppSource=$AppSource",
    "/DUpdaterSource=$UpdaterSource",
    "/DOutputDir=$OutputDir",
    "/DAppVersion=$AppVersion",
    "/DNumericVersion=$NumericVersion",
    "/DBuildId=$BuildId"
)
if ($SyntaxCheck) {
    $isccArgs = @('/DUnsignedSyntaxCheck=1') + $isccArgs
} else {
    $isccArgs = @("/Scertum=$CertumSignCommand") + $isccArgs
}
$isccArgs += $issPath
$compileLog = Join-Path $OutputDir 'installer-compile.log'
& $IsccPath @isccArgs 2>&1 | Tee-Object -FilePath $compileLog
if ($LASTEXITCODE -ne 0) {
    throw "ISCC failed with exit code $LASTEXITCODE; see $compileLog"
}
$compileText = Get-Content -LiteralPath $compileLog -Raw
$engineMatch = [regex]::Match(
    $compileText,
    'Compiler engine version:\s*(Inno Setup\s+[0-9.]+)'
)
if (-not $engineMatch.Success -or $engineMatch.Groups[1].Value -notmatch '6\.7\.3') {
    throw 'Compile log does not contain the verified Inno Setup 6.7.3 engine banner.'
}
$isccEngineVersion = $engineMatch.Groups[1].Value.Trim()
$installer = Join-Path $OutputDir 'KGNext-Win11-x64-Preview-Setup.exe'
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Compiler did not produce $installer"
}
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($SyntaxCheck) {
    if ($signature.Status -ne 'NotSigned') {
        throw "Syntax-check output must be unsigned, found $($signature.Status)"
    }
} else {
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate) {
        throw "Signed Setup is not valid: $($signature.Status)"
    }
    if ($null -eq $signature.TimeStamperCertificate) {
        throw 'Signed Setup has no timestamp countersignature.'
    }
}
$summary = [ordered]@{
    compiled_at = (Get-Date).ToUniversalTime().ToString('o')
    syntax_check = [bool]$SyntaxCheck
    app_source = $AppSource
    app_exe = 'KindergartenManager.exe'
    app_exe_sha256 = (Get-FileHash -LiteralPath $appExe -Algorithm SHA256).Hash.ToLowerInvariant()
    updater_source = $UpdaterSource
    updater_exe = 'KindergartenManagerUpdater.exe'
    updater_exe_sha256 = (Get-FileHash -LiteralPath $updaterExe -Algorithm SHA256).Hash.ToLowerInvariant()
    app_version = $AppVersion
    numeric_version = $NumericVersion
    build_id = $BuildId
    signed_inputs_only = $signedInputsOnly
    app_signature_status = if ($appSignature) { [string]$appSignature.Status } else { $null }
    app_signer_subject = if ($appSignature -and $appSignature.SignerCertificate) { $appSignature.SignerCertificate.Subject } else { $null }
    app_timestamp_subject = if ($appSignature -and $appSignature.TimeStamperCertificate) { $appSignature.TimeStamperCertificate.Subject } else { $null }
    updater_signature_status = if ($updaterSignature) { [string]$updaterSignature.Status } else { $null }
    updater_signer_subject = if ($updaterSignature -and $updaterSignature.SignerCertificate) { $updaterSignature.SignerCertificate.Subject } else { $null }
    updater_timestamp_subject = if ($updaterSignature -and $updaterSignature.TimeStamperCertificate) { $updaterSignature.TimeStamperCertificate.Subject } else { $null }
    release_config_sha256 = if ($appConfig) { $appConfig.sha256 } else { $null }
    release_configs_identical = if ($appConfig -and $updaterConfig) { $appConfig.sha256 -eq $updaterConfig.sha256 } else { $null }
    iscc = $IsccPath
    iscc_file_version_metadata = $isccInfo.FileVersion
    iscc_engine_version = $isccEngineVersion
    iscc_signature_status = [string]$isccSignature.Status
    iscc_signer_subject = if ($isccSignature.SignerCertificate) { $isccSignature.SignerCertificate.Subject } else { $null }
    installer = $installer
    installer_bytes = (Get-Item -LiteralPath $installer).Length
    installer_sha256 = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    signature_status = [string]$signature.Status
    signer_subject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    signer_thumbprint = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint } else { $null }
    timestamp_subject = if ($signature.TimeStamperCertificate) { $signature.TimeStamperCertificate.Subject } else { $null }
    timestamp_not_after = if ($signature.TimeStamperCertificate) { $signature.TimeStamperCertificate.NotAfter.ToString('o') } else { $null }
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $OutputDir 'build-summary.json') -Encoding utf8
$summary | ConvertTo-Json -Depth 4
