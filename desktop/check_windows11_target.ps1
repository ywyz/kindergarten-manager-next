#Requires -Version 5.1
<#
Read-only Windows 11 target preflight for KGNext-E14. It never launches the app
or changes registry/policy/trust/MOTW. Optional report is a new isolated file
with no host/user/SID/paths/secrets. Exit 0 pass, 1 required failure, 2 incomplete.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExtractRoot,
    [Parameter(Mandatory = $true)][string]$ArchivePath,
    [Parameter(Mandatory = $true)][string]$ExpectedArchiveSha256,
    [Parameter(Mandatory = $true)][string]$ExpectedBuildId,
    [Parameter(Mandatory = $true)][string]$ExpectedDatabaseRevision,
    [string]$DataRoot = '',
    [string]$CredentialRoot = '',
    [string]$ReportPath = ''
)
$ErrorActionPreference = 'Stop'
$script:Product = 'KGNext-E14'
$script:Readme = 'README-KGNext-E14-win11-r01.txt'
$script:Manifest = 'package-files.json'
$script:Sums = 'SHA256SUMS.txt'
$script:ArchiveName = 'KGNext-E14-win11-r01.zip'
$script:MaxFiles = 20000
$script:MaxFileBytes = 1073741824
$script:MaxTotalBytes = 3221225472
$script:Checks = New-Object System.Collections.ArrayList
$script:Ids = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
$script:Reserved = @('CON','PRN','AUX','NUL','COM1','COM2','COM3','COM4','COM5','COM6','COM7','COM8','COM9','LPT1','LPT2','LPT3','LPT4','LPT5','LPT6','LPT7','LPT8','LPT9')

function Ck {
    param([string]$Id, [bool]$Req, [string]$St, [string]$Detail)
    [void]$script:Ids.Add($Id)
    [void]$script:Checks.Add([pscustomobject][ordered]@{ id=$Id; required=$Req; status=$St; detail=$Detail })
}

function Norm {
    param([string]$p)
    $f = [System.IO.Path]::GetFullPath($p)
    if ($f.Length -gt 3 -and ($f.EndsWith('\') -or $f.EndsWith('/'))) { $f = $f.TrimEnd([char[]]@('\','/')) }
    return $f
}

function Within {
    param([string]$c, [string]$p)
    if ([string]::IsNullOrWhiteSpace($c) -or [string]::IsNullOrWhiteSpace($p)) { return $false }
    $c = Norm $c; $p = Norm $p
    if ([string]::Equals($c,$p,[System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    if (-not $p.EndsWith('\')) { $p = $p + '\' }
    return $c.StartsWith($p,[System.StringComparison]::OrdinalIgnoreCase)
}
function Sha {
    param([string]$p)
    $s = $null; $h = $null
    try {
        $s = [System.IO.File]::Open($p,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::Read)
        $h = [System.Security.Cryptography.SHA256]::Create()
        return ([System.BitConverter]::ToString($h.ComputeHash($s))).Replace('-','').ToLowerInvariant()
    } finally {
        if ($null -ne $h) { $h.Dispose() }
        if ($null -ne $s) { $s.Dispose() }
    }
}

function ReadText {
    param([string]$p, [long]$max)
    $i = Get-Item -LiteralPath $p -Force -ErrorAction Stop
    if ([long]$i.Length -gt $max) { throw 'too_large' }
    $e = New-Object System.Text.UTF8Encoding($false,$true)
    $t = [System.IO.File]::ReadAllText($p,$e)
    if ($t.Length -gt 0 -and [int][char]$t[0] -eq 0xFEFF) { $t = $t.Substring(1) }
    return $t
}
function KeysOk {
    param($o, [string[]]$a)
    if ($null -eq $o -or $o -isnot [System.Management.Automation.PSCustomObject]) { return $false }
    $n = @($o.PSObject.Properties.Name)
    if ($n.Count -ne $a.Count) { return $false }
    foreach ($x in $n) { if (-not ($a -ccontains $x)) { return $false } }
    return $true
}

function SafeRel {
    param([string]$p)
    if ([string]::IsNullOrEmpty($p)) { return 'empty' }
    if ($p.Length -gt 1000) { return 'too_long' }
    if ($p.IndexOf('\') -ge 0) { return 'backslash' }
    if ($p.StartsWith('/')) { return 'rooted' }
    if ($p.IndexOf(':') -ge 0) { return 'colon_or_ads' }
    foreach ($ch in $p.ToCharArray()) { if ([char]::IsControl($ch)) { return 'control' } }
    foreach ($part in $p.Split('/')) {
        if ($part.Length -eq 0) { return 'empty_segment' }
        if ($part -eq '.' -or $part -eq '..') { return 'dot_segment' }
        if ($part.EndsWith('.') -or $part.EndsWith(' ')) { return 'trailing_dot_space' }
        if ($part.IndexOfAny([char[]]@('"','<','>','|','?','*')) -ge 0) { return 'invalid_char' }
        if ($script:Reserved -contains $part.Split('.')[0].ToUpperInvariant()) { return 'reserved_name' }
    }
    return $null
}

function SafeSum {
    param([string]$p)
    if ([string]::IsNullOrEmpty($p)) { return [pscustomobject]@{ok=$false;kind='';rel=''} }
    if ($p -ceq $script:Readme -or $p -ceq $script:Manifest) { return [pscustomobject]@{ok=$true;kind='outer';rel=$p} }
    $pre = $script:Product + '/'
    if ($p.StartsWith($pre,[System.StringComparison]::Ordinal)) {
        $rel = $p.Substring($pre.Length)
        if ($null -ne (SafeRel $rel)) { return [pscustomobject]@{ok=$false;kind='';rel=''} }
        return [pscustomobject]@{ok=$true;kind='product';rel=$rel}
    }
    return [pscustomobject]@{ok=$false;kind='';rel=''}
}
function PeMachine {
    param([string]$p)
    $s = $null; $r = $null
    try {
        $s = [System.IO.File]::Open($p,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::Read)
        if ($s.Length -lt 64) { return $null }
        $r = New-Object System.IO.BinaryReader($s)
        if ($r.ReadUInt16() -ne 0x5A4D) { return $null }
        $s.Position = 0x3C
        $off = $r.ReadInt32()
        if ($off -lt 0 -or ($off + 6) -gt $s.Length) { return $null }
        $s.Position = $off
        if ($r.ReadUInt32() -ne 0x00004550) { return $null }
        return [int]$r.ReadUInt16()
    } catch { return $null } finally {
        if ($null -ne $r) { $r.Dispose() }
        if ($null -ne $s) { $s.Dispose() }
    }
}

function RegVal {
    param([string]$key, [string]$name)
    try { $exists = Test-Path -LiteralPath $key -ErrorAction Stop } catch { return [pscustomobject]@{state='denied';value=$null} }
    if (-not $exists) { return [pscustomobject]@{state='missing';value=$null} }
    try {
        $item = Get-ItemProperty -LiteralPath $key -ErrorAction Stop
        $prop = $item.PSObject.Properties[$name]
        if ($null -eq $prop) { return [pscustomobject]@{state='missing';value=$null} }
        return [pscustomobject]@{state='ok';value=$prop.Value}
    } catch { return [pscustomobject]@{state='denied';value=$null} }
}
function FileState {
    param([string]$p)
    $r = [pscustomobject][ordered]@{exists=$false;is_file=$false;reparse=$null;length=[long]0;state='ok'}
    try {
        $i = Get-Item -LiteralPath $p -Force -ErrorAction Stop
        $r.exists = $true
        $r.is_file = -not [bool]$i.PSIsContainer
        $r.reparse = ((([int]$i.Attributes) -band ([int][System.IO.FileAttributes]::ReparsePoint)) -ne 0)
        if ($r.is_file) { $r.length = [long]$i.Length }
        return $r
    } catch [System.Management.Automation.ItemNotFoundException] { return $r } catch { $r.state = 'unknown'; return $r }
}

function DirState {
    param([string]$p)
    $r = [pscustomobject][ordered]@{exists=$false;is_dir=$false;reparse=$null;state='ok'}
    try {
        $i = Get-Item -LiteralPath $p -Force -ErrorAction Stop
        $r.exists = $true
        $r.is_dir = [bool]$i.PSIsContainer
        $r.reparse = ((([int]$i.Attributes) -band ([int][System.IO.FileAttributes]::ReparsePoint)) -ne 0)
        return $r
    } catch [System.Management.Automation.ItemNotFoundException] { return $r } catch { $r.state = 'unknown'; return $r }
}

function PathExistence {
    param([string]$p, [string]$db)
    $r = [pscustomobject][ordered]@{provided=$false;exists=$false;is_dir=$false;reparse=$null;has_db=$false;state='ok'}
    if ([string]::IsNullOrWhiteSpace($p)) { return $r }
    $r.provided = $true
    $d = DirState $p
    $r.exists = $d.exists; $r.is_dir = $d.is_dir; $r.reparse = $d.reparse; $r.state = $d.state
    if ($d.state -eq 'ok' -and $d.exists -and $d.is_dir -and -not [string]::IsNullOrWhiteSpace($db)) {
        try { $r.has_db = [bool](Test-Path -LiteralPath (Join-Path $p $db)) } catch { $r.state = 'unknown' }
    }
    return $r
}
function ProductTree {
    param([string]$root)
    $files = New-Object System.Collections.ArrayList
    $errors = New-Object System.Collections.ArrayList
    $dirs = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $stack = New-Object System.Collections.Stack
    $rootFull = [System.IO.Path]::GetFullPath($root)
    $stack.Push($rootFull)
    while ($stack.Count -gt 0) {
        $dir = [string]$stack.Pop()
        if (-not $dirs.Add($dir)) { continue }
        try { $entries = [System.IO.Directory]::GetFileSystemEntries($dir) } catch { [void]$errors.Add('read_directory'); continue }
        foreach ($entry in $entries) {
            try { $attr = [System.IO.File]::GetAttributes($entry) } catch { [void]$errors.Add('read_attributes'); continue }
            if ((([int]$attr) -band ([int][System.IO.FileAttributes]::ReparsePoint)) -ne 0) { [void]$errors.Add('reparse_point'); continue }
            if ((([int]$attr) -band ([int][System.IO.FileAttributes]::Directory)) -ne 0) { $stack.Push($entry); continue }
            [void]$files.Add($entry.Substring($rootFull.Length).TrimStart([char[]]@('\','/')).Replace('\','/'))
        }
    }
    return [pscustomobject]@{files=$files;errors=$errors;dirs=$dirs.Count}
}
function SigState {
    param([string]$p)
    try {
        $s = Get-AuthenticodeSignature -LiteralPath $p -ErrorAction Stop
        $st = [string]$s.Status
        if ([string]::IsNullOrWhiteSpace($st)) { return [pscustomobject]@{state='unknown';status='unknown';integrity='unknown';detail='empty'} }
        if ($st -eq 'HashMismatch') { return [pscustomobject]@{state='ok';status=$st;integrity='fail';detail='hash_mismatch'} }
        if ($st -eq 'NotSupportedFileFormat') { return [pscustomobject]@{state='ok';status=$st;integrity='fail';detail='not_supported'} }
        if ($st -eq 'UnknownError' -or $st -eq 'Incompatible') { return [pscustomobject]@{state='ok';status=$st;integrity='unknown';detail='unknown'} }
        return [pscustomobject]@{state='ok';status=$st;integrity='pass';detail='read'}
    } catch {
        return [pscustomobject]@{state='unknown';status='unknown';integrity='unknown';detail='read_failed'}
    }
}

function WebView2State {
    $guid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    $items = @(
        [pscustomobject]@{source='HKCU';path=('HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\'+$guid)},
        [pscustomobject]@{source='HKLM-WOW6432';path=('HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\'+$guid)},
        [pscustomobject]@{source='HKLM';path=('HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\'+$guid)}
    )
    $denied = $false; $invalid = $false
    foreach ($it in $items) {
        $v = RegVal $it.path 'pv'
        if ($v.state -eq 'denied') { $denied = $true; continue }
        if ($v.state -ne 'ok') { continue }
        $text = [string]$v.value
        if ([string]::IsNullOrWhiteSpace($text)) { $invalid = $true; continue }
        $ver = $null
        if (-not [version]::TryParse($text,[ref]$ver)) { $invalid = $true; continue }
        if ($ver -gt [version]'0.0.0.0') { return [pscustomobject]@{state='found';version=$ver.ToString();source=$it.source;detail='version'} }
    }
    if ($invalid) { return [pscustomobject]@{state='unknown';version='';source='';detail='invalid_version'} }
    if ($denied) { return [pscustomobject]@{state='unknown';version='';source='';detail='access_denied'} }
    return [pscustomobject]@{state='missing';version='';source='';detail='zero_or_absent'}
}
function SacState {
    $v = RegVal 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' 'VerifiedAndReputablePolicyState'
    if ($v.state -ne 'ok' -or $null -eq $v.value -or $v.value -is [bool]) { return [pscustomobject]@{state=$v.state;number=$null;label='unknown'} }
    $n = 0
    if (-not [int]::TryParse([string]$v.value,[ref]$n)) { return [pscustomobject]@{state='invalid';number=$null;label='unknown'} }
    if ($n -eq 0) { return [pscustomobject]@{state='ok';number=0;label='off'} }
    if ($n -eq 1) { return [pscustomobject]@{state='ok';number=1;label='enforce'} }
    if ($n -eq 2) { return [pscustomobject]@{state='ok';number=2;label='evaluation'} }
    return [pscustomobject]@{state='invalid';number=$null;label='unknown'}
}

function WdacState {
    $win = [string]$env:WINDIR
    if ([string]::IsNullOrWhiteSpace($win)) { return [pscustomobject]@{state='unknown';count=$null} }
    $dir = Join-Path $win 'System32\CodeIntegrity\CiPolicies\Active'
    try {
        [void](Get-Item -LiteralPath $dir -Force -ErrorAction Stop)
        return [pscustomobject]@{state='ok';count=([System.IO.Directory]::GetFiles($dir,'*.cip')).Length}
    } catch [System.Management.Automation.ItemNotFoundException] { return [pscustomobject]@{state='ok';count=0} } catch { return [pscustomobject]@{state='unknown';count=$null} }
}
function ReportPathOk {
    param([string]$p,[string]$extract,[string]$product,[string]$archive,[string]$data,[string]$cred,[string]$appRoot,[string[]]$extraRoots)
    AssertRawPath $p 'report_path'
    $full = [System.IO.Path]::GetFullPath($p)
    AssertAncestors $full 'none' 'report_path'
    $parent = [System.IO.Path]::GetDirectoryName($full)
    if ([string]::IsNullOrEmpty($parent) -or -not (Test-Path -LiteralPath $parent -PathType Container)) { throw 'report_parent_missing' }
    foreach ($root in @($extract,$product,$archive,$data,$cred,$appRoot)) {
        if (-not [string]::IsNullOrWhiteSpace($root) -and (Overlaps $full $root)) { throw 'report_path_inside_protected_root' }
    }
    foreach ($root in @($extraRoots)) {
        if (-not [string]::IsNullOrWhiteSpace($root) -and (Overlaps $full $root)) { throw 'report_path_inside_protected_root' }
    }
    return $full
}
function WriteReport {
    param([string]$p,[string]$json)
    $parent = [System.IO.Path]::GetDirectoryName($p)
    $tmp = Join-Path $parent ('.kgm-preflight-'+[Guid]::NewGuid().ToString('N')+'.tmp')
    $e = New-Object System.Text.UTF8Encoding($false)
    try {
        [System.IO.File]::WriteAllText($tmp,$json+"`r`n",$e)
        [System.IO.File]::Move($tmp,$p)
    } finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
    }
}

function MotwState {
    param([string]$p)
    try {
        $s = Get-Item -LiteralPath $p -Stream 'Zone.Identifier' -ErrorAction Stop
        if ($null -ne $s) { return 'present' }
        return 'absent'
    } catch {
        $t = $_.Exception.GetType().Name
        if ($t -eq 'ItemNotFoundException' -or $t -eq 'FileNotFoundException') { return 'absent' }
        return 'unknown'
    }
}
function Overlaps {
    param([string]$A, [string]$B)
    if ([string]::IsNullOrWhiteSpace($A) -or [string]::IsNullOrWhiteSpace($B)) { return $false }
    return ((Within $A $B) -or (Within $B $A))
}

function AssertRawPath {
    param([string]$Raw, [string]$Label)
    if ([string]::IsNullOrWhiteSpace($Raw)) { throw ($Label + '_empty') }
    if (-not [System.IO.Path]::IsPathRooted($Raw)) { throw ($Label + '_not_absolute') }
    if ($Raw -match '^[\\/]{2}') { throw ($Label + '_unc_or_device') }
    if ($Raw -match '^[A-Za-z]:(?![\\/])') { throw ($Label + '_drive_relative') }
    foreach ($part in ($Raw -split '[\\/]+')) {
        if ($part.Trim() -eq '..') { throw ($Label + '_raw_dotdot') }
    }
}

function AssertAncestors {
    param([string]$Full, [string]$Role, [string]$Label)
    $cur = $Full
    $first = $true
    while (-not [string]::IsNullOrWhiteSpace($cur)) {
        $item = $null
        try { $item = Get-Item -LiteralPath $cur -Force -ErrorAction Stop }
        catch [System.Management.Automation.ItemNotFoundException] { $item = $null }
        catch { throw ($Label + '_ancestor_unknown') }
        if ($null -ne $item) {
            if ((([int]$item.Attributes) -band ([int][System.IO.FileAttributes]::ReparsePoint)) -ne 0) { throw ($Label + '_ancestor_reparse') }
            if ($first) {
                if ($Role -eq 'directory' -and -not [bool]$item.PSIsContainer) { throw ($Label + '_role_conflict') }
                if ($Role -eq 'file' -and [bool]$item.PSIsContainer) { throw ($Label + '_role_conflict') }
                if ($Role -eq 'none') { throw ($Label + '_exists') }
            } elseif (-not [bool]$item.PSIsContainer) { throw ($Label + '_ancestor_is_file') }
        }
        $parent = [System.IO.Path]::GetDirectoryName($cur)
        if ([string]::IsNullOrEmpty($parent) -or $parent -eq $cur) { break }
        $cur = $parent
        $first = $false
    }
}
function NativeArch {
    try { $items = @(Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop) }
    catch { return [pscustomobject]@{state='unknown';arch='';codes='';detail='cim_failed'} }
    if ($items.Count -lt 1) { return [pscustomobject]@{state='unknown';arch='';codes='';detail='cim_empty'} }
    $codes = New-Object System.Collections.ArrayList
    foreach ($item in $items) {
        if ($null -eq $item.Architecture -or $item.Architecture -is [bool]) { return [pscustomobject]@{state='unknown';arch='';codes='';detail='cim_value'} }
        $code = 0
        if (-not [int]::TryParse([string]$item.Architecture,[ref]$code)) { return [pscustomobject]@{state='unknown';arch='';codes='';detail='cim_value'} }
        if (-not $codes.Contains($code)) { [void]$codes.Add($code) }
    }
    $codesText = ($codes | Sort-Object) -join ','
    if ($codes.Count -ne 1) { return [pscustomobject]@{state='unknown';arch='';codes=$codesText;detail='cim_conflict'} }
    $code = [int]$codes[0]
    if ($code -eq 9) { return [pscustomobject]@{state='ok';arch='AMD64';codes=$codesText;detail='cim'} }
    if ($code -eq 12) { return [pscustomobject]@{state='ok';arch='ARM64';codes=$codesText;detail='cim'} }
    if ($code -eq 0) { return [pscustomobject]@{state='ok';arch='X86';codes=$codesText;detail='cim'} }
    return [pscustomobject]@{state='unknown';arch='';codes=$codesText;detail='cim_unknown_code'}
}
function PeInventory {
    param([string]$Product, $Tree)
    $list = New-Object System.Collections.ArrayList
    $total = 0; $notSigned = 0; $valid = 0; $other = 0; $bad = 0; $unknown = 0
    if ($null -eq $Tree) {
        return [pscustomobject]@{state='unknown';list=$list;total=0;not_signed=0;valid=0;other=0;bad=0;unknown=0}
    }
    foreach ($rel in $Tree.files) {
        $ext = [System.IO.Path]::GetExtension($rel).ToLowerInvariant()
        if ($ext -ne '.exe' -and $ext -ne '.dll' -and $ext -ne '.pyd') { continue }
        $total++
        $full = [System.IO.Path]::GetFullPath((Join-Path $Product $rel.Replace('/','\')))
        $fs = FileState $full
        if (-not $fs.exists -or -not $fs.is_file -or $fs.reparse -eq $true -or $fs.state -ne 'ok') {
            $unknown++
            [void]$list.Add([pscustomobject][ordered]@{path=$rel;status='read_error';integrity='unknown'})
            continue
        }
        $mach = PeMachine $full
        if ($null -eq $mach) {
            $bad++
            [void]$list.Add([pscustomobject][ordered]@{path=$rel;status='not_pe';integrity='fail'})
            continue
        }
        $sg = SigState $full
        if ($sg.state -ne 'ok') {
            $unknown++
            [void]$list.Add([pscustomobject][ordered]@{path=$rel;status='unknown';integrity='unknown'})
            continue
        }
        if ($sg.status -eq 'NotSigned') { $notSigned++ }
        elseif ($sg.status -eq 'Valid') { $valid++ }
        else { $other++ }
        if ($sg.integrity -eq 'fail') { $bad++ }
        elseif ($sg.integrity -eq 'unknown') { $unknown++ }
        [void]$list.Add([pscustomobject][ordered]@{path=$rel;status=$sg.status;integrity=$sg.integrity})
    }
    return [pscustomobject]@{state='ok';list=$list;total=$total;not_signed=$notSigned;valid=$valid;other=$other;bad=$bad;unknown=$unknown}
}
function Main {
    $started = [DateTime]::UtcNow
    $runId = [Guid]::NewGuid().ToString()
    $req = New-Object System.Collections.ArrayList
    foreach ($id in @(
        'ps_version_supported','os_registry_readable','os_windows11','os_arch_known','os_arch_supported',
        'webview2_runtime','sac_policy_state','wdac_policy_state','archive_present','archive_regular_file',
        'archive_sha256_match','extract_root_valid','outer_tree_exact','readme_present','manifest_present',
        'sums_present','manifest_json_valid','manifest_schema','manifest_paths_safe','manifest_paths_unique',
        'manifest_sorted','product_root_valid','product_tree_exact','product_sizes_hashes','package_info_present',
        'package_info_schema','package_info_identity','build_identity_present','build_identity_schema',
        'build_identity_expected','main_exe_present','main_exe_pe_amd64','main_exe_signature_readable',
        'main_exe_signature_integrity','pe_signature_inventory','pe_signature_integrity','sums_format','sums_paths_safe','sums_exact_set','sums_hashes_match',
        'default_data_existence','default_credentials_existence'
    )) { [void]$req.Add($id) }
    AssertRawPath $ExtractRoot 'extract_root'
    AssertRawPath $ArchivePath 'archive_path'
    $extract = [System.IO.Path]::GetFullPath($ExtractRoot)
    $archive = [System.IO.Path]::GetFullPath($ArchivePath)
    $product = [System.IO.Path]::Combine($extract,$script:Product)
    AssertAncestors $extract 'directory' 'extract_root'
    AssertAncestors $archive 'file' 'archive_path'
    AssertAncestors $product 'directory' 'product_root'
    $expectedHash = ([string]$ExpectedArchiveSha256).Trim().ToLowerInvariant()
    if ($expectedHash -notmatch '^[0-9a-f]{64}$') { throw 'input_archive_sha_invalid' }
    $eg = [Guid]::Empty
    if (-not [Guid]::TryParse($ExpectedBuildId,[ref]$eg)) { throw 'input_expected_build_id_invalid' }
    if ($ExpectedDatabaseRevision -notmatch '^[0-9]{8}_[0-9]{4}_[A-Za-z0-9_]+$') { throw 'input_expected_revision_invalid' }
    $expectedBuild = $eg.ToString()
    $data = ''
    $cred = ''
    if (-not [string]::IsNullOrWhiteSpace($DataRoot)) {
        AssertRawPath $DataRoot 'data_root'
        $data = [System.IO.Path]::GetFullPath($DataRoot)
        AssertAncestors $data 'directory' 'data_root'
        [void]$req.Add('data_root_isolation')
    }
    if (-not [string]::IsNullOrWhiteSpace($CredentialRoot)) {
        AssertRawPath $CredentialRoot 'credential_root'
        $cred = [System.IO.Path]::GetFullPath($CredentialRoot)
        AssertAncestors $cred 'directory' 'credential_root'
        [void]$req.Add('credential_root_isolation')
    }
    $local = [string]$env:LOCALAPPDATA
    $appRoot = ''; $defData = ''; $defCred = ''
    if (-not [string]::IsNullOrWhiteSpace($local)) {
        $appRoot = [System.IO.Path]::Combine($local,'KindergartenManager')
        $defData = [System.IO.Path]::Combine($appRoot,'data')
        $defCred = [System.IO.Path]::Combine($appRoot,'credentials')
    }
    $scriptPath = [string]$PSCommandPath
    $scriptRoot = [string]$PSScriptRoot
    $sourceRoots = @()
    if (-not [string]::IsNullOrWhiteSpace($scriptPath)) { $sourceRoots += $scriptPath }
    if (-not [string]::IsNullOrWhiteSpace($scriptRoot)) {
        if (Test-Path -LiteralPath (Join-Path $scriptRoot '.git')) { $sourceRoots += $scriptRoot }
        else {
            $scriptParent = [System.IO.Path]::GetDirectoryName($scriptRoot)
            if (-not [string]::IsNullOrWhiteSpace($scriptParent) -and (Test-Path -LiteralPath (Join-Path $scriptParent '.git'))) { $sourceRoots += $scriptParent }
        }
    }
    $reportFull = ''
    $reportReq = -not [string]::IsNullOrWhiteSpace($ReportPath)
    if ($reportReq) {
        $reportFull = ReportPathOk $ReportPath $extract $product $archive $data $cred $appRoot $sourceRoots
        [void]$req.Add('report_output_isolation')
        Ck 'report_output_isolation' $true 'pass' 'validated'
    } else {
        Ck 'report_output_isolation' $false 'not_run' 'none'
        Ck 'report_written' $false 'not_run' 'none'
    }
    $psv = [string]$PSVersionTable.PSVersion
    $psMajor = [int]$PSVersionTable.PSVersion.Major
    $psEd = [string]$PSVersionTable.PSEdition
    if ($psMajor -ge 5) { Ck 'ps_version_supported' $true 'pass' 'ok' } else { Ck 'ps_version_supported' $true 'fail' 'unsupported' }
    $osKey = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
    $pn = RegVal $osKey 'ProductName'; $bv = RegVal $osKey 'CurrentBuild'; $uv = RegVal $osKey 'UBR'
    $dv = RegVal $osKey 'DisplayVersion'; $ev = RegVal $osKey 'EditionID'
    $osName = ''; $buildText = ''; $ubr = $null; $disp = ''; $edition = ''
    if ($pn.state -eq 'ok') { $osName = [string]$pn.value }
    if ($bv.state -eq 'ok') { $buildText = [string]$bv.value }
    if ($uv.state -eq 'ok' -and $uv.value -isnot [bool]) { $n = 0; if ([int]::TryParse([string]$uv.value,[ref]$n)) { $ubr = $n } }
    if ($dv.state -eq 'ok') { $disp = [string]$dv.value }
    if ($ev.state -eq 'ok') { $edition = [string]$ev.value }
    $build = 0; $buildSrc = 'registry'
    $buildParsed = [int]::TryParse($buildText,[ref]$build)
    if (-not $buildParsed) { $build = [Environment]::OSVersion.Version.Build; $buildParsed = $true; $buildSrc = 'dotnet' }
    if ($pn.state -eq 'ok' -and $bv.state -eq 'ok') { Ck 'os_registry_readable' $true 'pass' 'ok' } else { Ck 'os_registry_readable' $true 'unknown' 'registry_unreadable' }
    if ($buildParsed -and $build -ge 22000) { Ck 'os_windows11' $true 'pass' 'build' } elseif ($buildParsed) { Ck 'os_windows11' $true 'fail' 'not_windows11' } else { Ck 'os_windows11' $true 'unknown' 'build_unknown' }
    $procArch = [string]$env:PROCESSOR_ARCHITECTURE
    $wow = [string]$env:PROCESSOR_ARCHITEW6432
    $native = NativeArch
    $osArch = $native.arch
    $osArchSource = $native.detail
    $osCodes = $native.codes
    if ($native.state -eq 'ok') { Ck 'os_arch_known' $true 'pass' $osArchSource } else { Ck 'os_arch_known' $true 'unknown' $osArchSource }
    if ($native.state -ne 'ok') { Ck 'os_arch_supported' $true 'unknown' $osArchSource }
    elseif ($osArch -eq 'AMD64') { Ck 'os_arch_supported' $true 'pass' 'amd64' }
    elseif ($osArch -eq 'ARM64') { Ck 'os_arch_supported' $true 'fail' 'arm64_not_validated' }
    elseif ($osArch -eq 'X86') { Ck 'os_arch_supported' $true 'fail' 'x86_not_supported' }
    else { Ck 'os_arch_supported' $true 'unknown' 'arch_unknown' }
    $admin = $null
    try {
        $pr = New-Object System.Security.Principal.WindowsPrincipal([System.Security.Principal.WindowsIdentity]::GetCurrent())
        $admin = [bool]$pr.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
        Ck 'admin_context' $false 'pass' 'read'
    } catch { Ck 'admin_context' $false 'unknown' 'read_failed' }
    $execPolicy = 'unknown'
    try { $execPolicy = [string](Get-ExecutionPolicy) } catch { $execPolicy = 'unknown' }
    $wv = WebView2State
    if ($wv.state -eq 'found') { Ck 'webview2_runtime' $true 'pass' 'found' } elseif ($wv.state -eq 'unknown') { Ck 'webview2_runtime' $true 'unknown' $wv.detail } else { Ck 'webview2_runtime' $true 'fail' $wv.detail }
    $sac = SacState
    if ($sac.state -eq 'ok') { Ck 'sac_policy_state' $true 'pass' $sac.label } else { Ck 'sac_policy_state' $true 'unknown' $sac.state }
    $wdac = WdacState
    if ($wdac.state -eq 'ok') { Ck 'wdac_policy_state' $true 'pass' ('policies='+[string]$wdac.count) } else { Ck 'wdac_policy_state' $true 'unknown' 'access_denied' }
    $as = FileState $archive
    $actualHash = ''
    if (-not $as.exists) {
        Ck 'archive_present' $true 'fail' 'missing'; Ck 'archive_regular_file' $true 'fail' 'missing'; Ck 'archive_sha256_match' $true 'fail' 'missing'
    } elseif (-not $as.is_file) {
        Ck 'archive_present' $true 'pass' 'present'; Ck 'archive_regular_file' $true 'fail' 'not_a_file'; Ck 'archive_sha256_match' $true 'fail' 'not_a_file'
    } elseif ($as.reparse -eq $true) {
        Ck 'archive_present' $true 'pass' 'present'; Ck 'archive_regular_file' $true 'fail' 'reparse'; Ck 'archive_sha256_match' $true 'fail' 'reparse'
    } elseif ($as.state -ne 'ok') {
        Ck 'archive_present' $true 'unknown' 'stat_failed'; Ck 'archive_regular_file' $true 'unknown' 'stat_failed'; Ck 'archive_sha256_match' $true 'unknown' 'stat_failed'
    } else {
        Ck 'archive_present' $true 'pass' 'present'; Ck 'archive_regular_file' $true 'pass' 'regular'
        try { $actualHash = Sha $archive } catch { $actualHash = '' }
        if ($actualHash -eq '') { Ck 'archive_sha256_match' $true 'unknown' 'hash_failed' } elseif ($actualHash -ceq $expectedHash) { Ck 'archive_sha256_match' $true 'pass' 'match' } else { Ck 'archive_sha256_match' $true 'fail' 'mismatch' }
    }
    $es = DirState $extract
    if (-not $es.exists) { Ck 'extract_root_valid' $true 'fail' 'missing' } elseif (-not $es.is_dir) { Ck 'extract_root_valid' $true 'fail' 'not_a_directory' } elseif ($es.reparse -eq $true) { Ck 'extract_root_valid' $true 'fail' 'reparse' } elseif ($es.state -ne 'ok') { Ck 'extract_root_valid' $true 'unknown' 'stat_failed' } else { Ck 'extract_root_valid' $true 'pass' 'directory' }
    $outerOk = $false
    if ($es.state -eq 'ok' -and $es.exists -and $es.is_dir -and $es.reparse -ne $true) {
        try { $outer = @([System.IO.Directory]::GetFileSystemEntries($extract)) } catch { $outer = @() }
        $expectedOuter = @($script:Product,$script:Readme,$script:Manifest,$script:Sums)
        $names = @()
        foreach ($x in $outer) { $names += [System.IO.Path]::GetFileName($x) }
        if ($outer.Count -eq 4) {
            $outerOk = $true
            foreach ($n in $expectedOuter) { if (-not ($names -ccontains $n)) { $outerOk = $false } }
        }
        if ($outerOk) {
            $ps = DirState $product; $rs = FileState (Join-Path $extract $script:Readme)
            $ms = FileState (Join-Path $extract $script:Manifest); $ss = FileState (Join-Path $extract $script:Sums)
            if (-not $ps.is_dir -or $ps.reparse -eq $true) { $outerOk = $false }
            if (-not $rs.is_file -or $rs.reparse -eq $true) { $outerOk = $false }
            if (-not $ms.is_file -or $ms.reparse -eq $true) { $outerOk = $false }
            if (-not $ss.is_file -or $ss.reparse -eq $true) { $outerOk = $false }
        }
    }
    if ($outerOk) { Ck 'outer_tree_exact' $true 'pass' 'exact' } else { Ck 'outer_tree_exact' $true 'fail' 'unexpected_or_missing' }
    $readmeF = Join-Path $extract $script:Readme
    $manifestF = Join-Path $extract $script:Manifest
    $sumsF = Join-Path $extract $script:Sums
    $readmeS = FileState $readmeF; $manifestS = FileState $manifestF; $sumsS = FileState $sumsF
    if ($readmeS.is_file -and $readmeS.reparse -ne $true -and $readmeS.length -gt 0 -and $readmeS.length -le 8388608) { Ck 'readme_present' $true 'pass' 'regular' } else { Ck 'readme_present' $true 'fail' 'missing_or_invalid' }
    if ($manifestS.is_file -and $manifestS.reparse -ne $true -and $manifestS.length -gt 0) { Ck 'manifest_present' $true 'pass' 'regular' } else { Ck 'manifest_present' $true 'fail' 'missing_or_invalid' }
    if ($sumsS.is_file -and $sumsS.reparse -ne $true -and $sumsS.length -gt 0) { Ck 'sums_present' $true 'pass' 'regular' } else { Ck 'sums_present' $true 'fail' 'missing_or_invalid' }
    $manifest = $null; $jsonOk = $false
    if ($manifestS.is_file -and $manifestS.reparse -ne $true) {
        try { $manifest = ConvertFrom-Json -InputObject (ReadText $manifestF 67108864); $jsonOk = $true; Ck 'manifest_json_valid' $true 'pass' 'parsed' } catch { $manifest = $null; Ck 'manifest_json_valid' $true 'fail' 'invalid_json' }
    } else { Ck 'manifest_json_valid' $true 'fail' 'unavailable' }
    $schemaOk = $false
    $mBuild = ''; $mRev = ''; $mFreeze = ''; $mPkg = ''; $mGen = ''
    $mEntries = New-Object System.Collections.ArrayList
    $pathErrors = 0; $dupErrors = 0; $sortErrors = 0; $totalBytes = [long]0; $fileCount = 0
    if ($jsonOk) {
        $allowed = @('schema_version','package','build_id','database_revision','source_freeze_digest','generated_at','files')
        if (-not (KeysOk $manifest $allowed)) { Ck 'manifest_schema' $true 'fail' 'top_level_keys' }
        else {
            $sv = $manifest.schema_version
            $schemaField = (($sv -is [int]) -or ($sv -is [long])) -and ([long]$sv -eq 1)
            $packageField = ($manifest.package -is [string]) -and ($manifest.package -ceq $script:Product)
            $buildField = ($manifest.build_id -is [string])
            $revField = ($manifest.database_revision -is [string]) -and ($manifest.database_revision -match '^[0-9]{8}_[0-9]{4}_[A-Za-z0-9_]+$')
            $freezeField = ($manifest.source_freeze_digest -is [string]) -and ($manifest.source_freeze_digest -match '^[0-9a-fA-F]{64}$')
            $genField = $false
            if ($manifest.generated_at -is [DateTime] -or $manifest.generated_at -is [DateTimeOffset]) { $genField = $true }
            elseif ($manifest.generated_at -is [string]) { $dto = [DateTimeOffset]::MinValue; if ([DateTimeOffset]::TryParse([string]$manifest.generated_at,[ref]$dto)) { $genField = $true } }
            $filesField = $false
            if ($null -ne $manifest.files) { $fa = @($manifest.files); if ($fa.Count -ge 1 -and $fa.Count -le $script:MaxFiles) { $filesField = $true } }
            if ($schemaField -and $packageField -and $buildField -and $revField -and $freezeField -and $genField -and $filesField) {
                $schemaOk = $true
                $mBuild = [string]$manifest.build_id; $mRev = [string]$manifest.database_revision
                $mFreeze = ([string]$manifest.source_freeze_digest).ToLowerInvariant(); $mPkg = [string]$manifest.package; $mGen = [string]$manifest.generated_at
                Ck 'manifest_schema' $true 'pass' 'ok'
            } else { Ck 'manifest_schema' $true 'fail' 'field_or_type' }
        }
    } else { Ck 'manifest_schema' $true 'fail' 'unavailable' }
    $pathSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    $pathCi = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $pathNfc = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $anc = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    if ($schemaOk) {
        $fa = @($manifest.files); $prev = $null
        foreach ($it in $fa) {
            $okItem = KeysOk $it @('path','size','sha256')
            $p = $null; $sz = $null; $sh = $null
            if ($okItem) { $p = $it.path; $sz = $it.size; $sh = $it.sha256 }
            if (-not ($p -is [string])) { $pathErrors++; continue }
            if ($null -ne (SafeRel $p)) { $pathErrors++; continue }
            $sizeOk = $false; $sizeLong = [long]0
            if (-not ($sz -is [bool]) -and (($sz -is [int]) -or ($sz -is [long]))) { $sizeLong = [long]$sz; if ($sizeLong -ge 0 -and $sizeLong -le $script:MaxFileBytes) { $sizeOk = $true } }
            $shaOk = ($sh -is [string]) -and ($sh -cmatch '^[0-9a-f]{64}$')
            if (-not $sizeOk -or -not $shaOk) { $pathErrors++; continue }
            if (-not $pathSet.Add($p)) { $dupErrors++ }
            if (-not $pathCi.Add($p)) { $dupErrors++ }
            if (-not $pathNfc.Add($p.Normalize([System.Text.NormalizationForm]::FormC))) { $dupErrors++ }
            if ($null -ne $prev -and [string]::CompareOrdinal($prev,$p) -ge 0) { $sortErrors++ }
            $prev = $p
            $parts = $p.Split('/'); $pre = ''
            for ($i=0; $i -lt ($parts.Length-1); $i++) { if ($i -eq 0) { $pre = $parts[0] } else { $pre = $pre+'/'+$parts[$i] }; [void]$anc.Add($pre) }
            $totalBytes += $sizeLong; $fileCount++
            [void]$mEntries.Add([pscustomobject][ordered]@{path=$p;size=$sizeLong;sha256=[string]$sh})
        }
        if ($totalBytes -gt $script:MaxTotalBytes) { $pathErrors++ }
    }
    if (-not $schemaOk) { $pathErrors++ }
    if ($schemaOk) {
        foreach ($e in $mEntries) {
            $parts = $e.path.Split('/'); $pre = ''
            for ($i=0; $i -lt ($parts.Length-1); $i++) { if ($i -eq 0) { $pre = $parts[0] } else { $pre = $pre+'/'+$parts[$i] }; if ($pathCi.Contains($pre)) { $pathErrors++ } }
        }
    }
    if ($pathErrors -eq 0) { Ck 'manifest_paths_safe' $true 'pass' 'ok' } else { Ck 'manifest_paths_safe' $true 'fail' 'unsafe_or_invalid' }
    if ($schemaOk -and $dupErrors -eq 0) { Ck 'manifest_paths_unique' $true 'pass' 'ok' } else { Ck 'manifest_paths_unique' $true 'fail' 'duplicate_or_schema' }
    if ($schemaOk -and $sortErrors -eq 0) { Ck 'manifest_sorted' $true 'pass' 'ok' } else { Ck 'manifest_sorted' $true 'fail' 'not_sorted_or_schema' }
    $sumsMap = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([System.StringComparer]::Ordinal)
    $sumsCi = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $sumsNfc = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $sumsFormatOk = $false; $sumsPathErrors = 0; $sumsDup = 0; $sumsSort = 0; $sumsLines = 0; $sumsBad = 0
    if ($sumsS.is_file -and $sumsS.reparse -ne $true) {
        try {
            $lines = @((ReadText $sumsF 33554432) -split "`r?`n")
            $prev = $null
            foreach ($line in $lines) {
                if ($line.Length -eq 0) { continue }
                $match = [regex]::Match($line,'^([0-9a-f]{64})  (.+)$')
                if (-not $match.Success) { $sumsBad++; continue }
                $digest = $match.Groups[1].Value; $sp = $match.Groups[2].Value
                $sumInfo = SafeSum $sp
                if (-not $sumInfo.ok) { $sumsPathErrors++; continue }
                if ($sumsMap.ContainsKey($sp)) { $sumsDup++ } else { $sumsMap.Add($sp,$digest) }
                if (-not $sumsCi.Add($sp)) { $sumsDup++ }
                if (-not $sumsNfc.Add($sp.Normalize([System.Text.NormalizationForm]::FormC))) { $sumsDup++ }
                if ($null -ne $prev -and [string]::CompareOrdinal($prev,$sp) -ge 0) { $sumsSort++ }
                $prev = $sp; $sumsLines++
                $sumsFormatOk = $true
            }
            $sumsFormatOk = ($sumsLines -gt 0 -and $sumsBad -eq 0)
        } catch { $sumsFormatOk = $false }
    }
    if ($sumsFormatOk -and $sumsDup -eq 0 -and $sumsSort -eq 0) { Ck 'sums_format' $true 'pass' 'ok' } else { Ck 'sums_format' $true 'fail' 'format_or_order' }
    if ($sumsPathErrors -eq 0 -and $sumsS.is_file -and $sumsS.reparse -ne $true) { Ck 'sums_paths_safe' $true 'pass' 'ok' } else { Ck 'sums_paths_safe' $true 'fail' 'unsafe_path' }
    $sumsSetOk = $false; $sumsHashOk = $false
    if ($sumsFormatOk -and $sumsPathErrors -eq 0 -and $sumsDup -eq 0 -and $pathErrors -eq 0 -and $readmeS.is_file -and $manifestS.is_file) {
        $expectedSums = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
        foreach ($e in $mEntries) { [void]$expectedSums.Add($script:Product+'/'+$e.path) }
        [void]$expectedSums.Add($script:Readme); [void]$expectedSums.Add($script:Manifest)
        if ($sumsMap.Count -eq $expectedSums.Count) {
            $sumsSetOk = $true
            foreach ($x in $expectedSums) { if (-not $sumsMap.ContainsKey($x)) { $sumsSetOk = $false } }
            foreach ($x in $sumsMap.Keys) { if (-not $expectedSums.Contains($x)) { $sumsSetOk = $false } }
        }
        if ($sumsSetOk) {
            $sumsHashOk = $true
            foreach ($e in $mEntries) { $k = $script:Product+'/'+$e.path; if (-not $sumsMap.ContainsKey($k) -or $sumsMap[$k] -cne $e.sha256) { $sumsHashOk = $false } }
            try {
                $rd = Sha $readmeF; $md = Sha $manifestF
                if (-not $sumsMap.ContainsKey($script:Readme) -or $sumsMap[$script:Readme] -cne $rd) { $sumsHashOk = $false }
                if (-not $sumsMap.ContainsKey($script:Manifest) -or $sumsMap[$script:Manifest] -cne $md) { $sumsHashOk = $false }
            } catch { $sumsHashOk = $false }
        }
    }
    if ($sumsSetOk) { Ck 'sums_exact_set' $true 'pass' 'exact' } else { Ck 'sums_exact_set' $true 'fail' 'set_mismatch' }
    if ($sumsHashOk) { Ck 'sums_hashes_match' $true 'pass' 'ok' } else { Ck 'sums_hashes_match' $true 'fail' 'mismatch' }
    $pr = DirState $product
    if (-not $pr.exists) { Ck 'product_root_valid' $true 'fail' 'missing' } elseif (-not $pr.is_dir) { Ck 'product_root_valid' $true 'fail' 'not_a_directory' } elseif ($pr.reparse -eq $true) { Ck 'product_root_valid' $true 'fail' 'reparse' } elseif ($pr.state -ne 'ok') { Ck 'product_root_valid' $true 'unknown' 'stat_failed' } else { Ck 'product_root_valid' $true 'pass' 'directory' }
    $tree = $null; $treeOk = $false
    if ($pr.state -eq 'ok' -and $pr.exists -and $pr.is_dir -and $pr.reparse -ne $true) {
        $tree = ProductTree $product
        if ($tree.errors.Count -eq 0 -and $pathErrors -eq 0) {
            $actual = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
            foreach ($x in $tree.files) { [void]$actual.Add($x) }
            if ($actual.Count -eq $pathSet.Count) {
                $treeOk = $true
                foreach ($e in $mEntries) { if (-not $actual.Contains($e.path)) { $treeOk = $false } }
                foreach ($x in $actual) { if (-not $pathSet.Contains($x)) { $treeOk = $false } }
            }
        }
    }
    if ($treeOk) { Ck 'product_tree_exact' $true 'pass' 'exact' } else { Ck 'product_tree_exact' $true 'fail' 'set_mismatch_or_unreadable' }
    $mismatch = 0; $hashErr = 0; $actualTotal = [long]0
    if ($pathErrors -eq 0 -and $dupErrors -eq 0 -and $pr.state -eq 'ok' -and $pr.is_dir -and $pr.reparse -ne $true) {
        foreach ($e in $mEntries) {
            $full = [System.IO.Path]::GetFullPath((Join-Path $product $e.path.Replace('/','\')))
            if (-not (Within $full $product)) { $hashErr++; continue }
            $fs = FileState $full
            if (-not $fs.exists -or -not $fs.is_file -or $fs.reparse -eq $true -or $fs.state -ne 'ok') { $hashErr++; continue }
            $actualTotal += $fs.length
            if ($fs.length -ne $e.size) { $mismatch++; continue }
            try { if ((Sha $full) -cne $e.sha256) { $mismatch++ } } catch { $hashErr++ }
        }
        if ($actualTotal -ne $totalBytes) { $mismatch++ }
    } else { $hashErr++ }
    if ($mismatch -eq 0 -and $hashErr -eq 0) { Ck 'product_sizes_hashes' $true 'pass' 'ok' } else { Ck 'product_sizes_hashes' $true 'fail' ('mismatch='+[string]$mismatch+';errors='+[string]$hashErr) }
    $infoF = Join-Path $product 'package-info.json'
    $infoS = FileState $infoF
    $info = $null; $infoOk = $false
    if ($infoS.is_file -and $infoS.reparse -ne $true) {
        Ck 'package_info_present' $true 'pass' 'regular'
        try {
            $info = ConvertFrom-Json -InputObject (ReadText $infoF 4194304)
            $need = @('app','package','built_at','version','build_id','database_revision','build_identity','source_freeze_digest','pillow_version','pillow_license_included','pillow_license_sha256','pillow_plugins','migrations','templates','unsigned_internal_test','source_commit','frontend_digest','frontend_file_count')
            $missing = 0
            foreach ($n in $need) { if ($null -eq $info.PSObject.Properties[$n]) { $missing++ } }
            $coreOk = (
                $missing -eq 0 -and ($info.app -is [string]) -and ($info.app -ceq $script:Product) -and
                ($info.package -is [string]) -and ($info.package -ceq $script:Product) -and
                ($info.version -is [string]) -and ($info.version -match '^[0-9]+\.[0-9]+\.[0-9]+$') -and
                ($info.build_id -is [string]) -and ($info.database_revision -is [string]) -and
                ($info.database_revision -match '^[0-9]{8}_[0-9]{4}_[A-Za-z0-9_]+$') -and
                ($info.source_freeze_digest -is [string]) -and ($info.source_freeze_digest -match '^[0-9a-fA-F]{64}$') -and
                ($info.unsigned_internal_test -is [bool]) -and ($info.unsigned_internal_test -eq $true) -and
                ($info.source_commit -is [string]) -and ($info.source_commit -match '^[0-9a-fA-F]{40}$') -and
                ($info.frontend_digest -is [string]) -and ($info.frontend_digest -match '^[0-9a-fA-F]{64}$')
             )
            $infoBuilt = $false
            if ($info.built_at -is [DateTime] -or $info.built_at -is [DateTimeOffset]) { $infoBuilt = $true }
            elseif ($info.built_at -is [string]) { $bo = [DateTimeOffset]::MinValue; if ([DateTimeOffset]::TryParse([string]$info.built_at,[ref]$bo)) { $infoBuilt = $true } }
            $infoCountOk = $false
            if (-not ($info.frontend_file_count -is [bool]) -and (($info.frontend_file_count -is [int]) -or ($info.frontend_file_count -is [long]))) { if ([long]$info.frontend_file_count -ge 0) { $infoCountOk = $true } }
            $infoIdPath = ([string]$info.build_identity).Replace('\','/')
            $fieldsOk = $coreOk -and $infoBuilt -and $infoCountOk -and
                ($info.pillow_version -is [string]) -and ($info.pillow_version -ceq '13.0.0') -and
                ($info.pillow_license_included -is [bool]) -and ($info.pillow_license_included -eq $true) -and
                ($info.pillow_license_sha256 -is [string]) -and ($info.pillow_license_sha256 -cmatch '^[0-9a-f]{64}$') -and
                ($null -ne $info.pillow_plugins) -and (@($info.pillow_plugins).Count -ge 1) -and
                ($null -ne $info.migrations) -and (@($info.migrations).Count -ge 1) -and
                ($null -ne $info.templates) -and (@($info.templates).Count -ge 1) -and
                ($infoIdPath -ceq '_internal/build_identity.json')
            if ($fieldsOk) { $infoOk = $true; Ck 'package_info_schema' $true 'pass' 'ok' } else { Ck 'package_info_schema' $true 'fail' 'field_or_type' }
        } catch { Ck 'package_info_schema' $true 'fail' 'invalid_json' }
    } else {
        Ck 'package_info_present' $true 'fail' 'missing_or_invalid'
        Ck 'package_info_schema' $true 'fail' 'missing'
    }
    $infoIdOk = $false
    if ($infoOk) {
        $ig = [Guid]::Empty
        $igOk = [Guid]::TryParse([string]$info.build_id,[ref]$ig)
        if ($igOk -and $ig.ToString() -eq $expectedBuild -and [string]$info.database_revision -ceq $ExpectedDatabaseRevision -and ([string]$info.build_id) -ieq $mBuild -and ([string]$info.source_freeze_digest).ToLowerInvariant() -ceq $mFreeze) { $infoIdOk = $true; Ck 'package_info_identity' $true 'pass' 'ok' } else { Ck 'package_info_identity' $true 'fail' 'mismatch' }
    } else { Ck 'package_info_identity' $true 'fail' 'schema_invalid' }
    $idF = Join-Path $product '_internal\build_identity.json'
    $idS = FileState $idF
    $ident = $null; $idSchemaOk = $false
    if ($idS.is_file -and $idS.reparse -ne $true) {
        Ck 'build_identity_present' $true 'pass' 'regular'
        try {
            $ident = ConvertFrom-Json -InputObject (ReadText $idF 1048576)
            $allowedId = @('app_id','app_name','channel','version','build_id','package_format','platform','arch','python','database_revision')
            $idOk = KeysOk $ident $allowedId
            if ($idOk) {
                $idOk = ($ident.app_id -is [string]) -and ($ident.app_id -ceq 'kindergarten-manager-next') -and ($ident.app_name -is [string]) -and ($ident.app_name -ceq 'KindergartenManager') -and ($ident.channel -is [string]) -and ($ident.channel -ceq 'stable') -and
                    ($ident.version -is [string]) -and ($ident.version -match '^[0-9]+\.[0-9]+\.[0-9]+$') -and ($ident.build_id -is [string]) -and ($ident.package_format -is [string]) -and ($ident.package_format -ceq 'pyinstaller-onedir-zip-v1') -and
                    ($ident.platform -is [string]) -and ($ident.platform -ceq 'windows') -and ($ident.arch -is [string]) -and ($ident.arch -ceq 'x64') -and ($ident.python -is [string]) -and ($ident.python -ceq '3.14.7') -and
                    ($ident.database_revision -is [string]) -and ($ident.database_revision -match '^[0-9]{8}_[0-9]{4}_[A-Za-z0-9_]+$')
            }
            if ($idOk) { $idSchemaOk = $true; Ck 'build_identity_schema' $true 'pass' 'ok' } else { Ck 'build_identity_schema' $true 'fail' 'field_or_type' }
        } catch { Ck 'build_identity_schema' $true 'fail' 'invalid_json' }
    } else {
        Ck 'build_identity_present' $true 'fail' 'missing_or_invalid'
        Ck 'build_identity_schema' $true 'fail' 'missing'
    }
    $idExpectedOk = $false
    if ($idSchemaOk) {
        $gg = [Guid]::Empty
        $ggOk = [Guid]::TryParse([string]$ident.build_id,[ref]$gg)
        if ($ggOk -and $gg.ToString() -eq $expectedBuild -and [string]$ident.database_revision -ceq $ExpectedDatabaseRevision -and ([string]$ident.build_id) -ieq $mBuild -and [string]$ident.database_revision -ceq $mRev) { $idExpectedOk = $true; Ck 'build_identity_expected' $true 'pass' 'ok' } else { Ck 'build_identity_expected' $true 'fail' 'mismatch' }
    } else { Ck 'build_identity_expected' $true 'fail' 'schema_invalid' }
    $exeF = Join-Path $product ($script:Product+'.exe')
    $exeS = FileState $exeF
    $peLabel = 'unknown'
    if ($exeS.is_file -and $exeS.reparse -ne $true) {
        Ck 'main_exe_present' $true 'pass' 'regular'
        $mach = PeMachine $exeF
        if ($mach -eq 0x8664) { $peLabel = 'AMD64'; Ck 'main_exe_pe_amd64' $true 'pass' 'amd64' }
        elseif ($mach -eq 0xAA64) { $peLabel = 'ARM64'; Ck 'main_exe_pe_amd64' $true 'fail' 'arm64' }
        elseif ($mach -eq 0x014C) { $peLabel = 'x86'; Ck 'main_exe_pe_amd64' $true 'fail' 'x86' }
        else { Ck 'main_exe_pe_amd64' $true 'fail' 'not_pe_or_unknown' }
    } else {
        Ck 'main_exe_present' $true 'fail' 'missing_or_invalid'
        Ck 'main_exe_pe_amd64' $true 'fail' 'exe_missing'
    }
    $sig = [pscustomobject]@{state='unknown';status='unknown';integrity='unknown';detail='not_run'}
    if ($exeS.is_file -and $exeS.reparse -ne $true) { $sig = SigState $exeF }
    if ($sig.state -eq 'ok') {
        Ck 'main_exe_signature_readable' $true 'pass' 'read'
        Ck 'main_exe_signature_integrity' $true $sig.integrity $sig.detail
    } else {
        Ck 'main_exe_signature_readable' $true 'unknown' 'read_failed'
        Ck 'main_exe_signature_integrity' $true 'unknown' 'read_failed'
    }

    $pe = PeInventory $product $tree
    if ($pe.state -ne 'ok') {
        Ck 'pe_signature_inventory' $true 'unknown' 'tree_unavailable'
        Ck 'pe_signature_integrity' $true 'unknown' 'tree_unavailable'
    } elseif ($pe.bad -gt 0) {
        Ck 'pe_signature_inventory' $true 'fail' ('bad='+[string]$pe.bad+';count='+[string]$pe.total)
        Ck 'pe_signature_integrity' $true 'fail' 'bad_signature'
    } elseif ($pe.unknown -gt 0) {
        Ck 'pe_signature_inventory' $true 'unknown' ('unknown='+[string]$pe.unknown+';count='+[string]$pe.total)
        Ck 'pe_signature_integrity' $true 'unknown' 'read_error'
    } elseif ($pe.total -eq 0) {
        Ck 'pe_signature_inventory' $true 'fail' 'no_pe'
        Ck 'pe_signature_integrity' $true 'fail' 'no_pe'
    } else {
        Ck 'pe_signature_inventory' $true 'pass' ('count='+[string]$pe.total)
        Ck 'pe_signature_integrity' $true 'pass' 'ok'
    }
    $defDataS = PathExistence $defData 'kindergarten.db'
    $defCredS = PathExistence $defCred ''
    if ($defDataS.state -eq 'ok') { Ck 'default_data_existence' $true 'pass' 'read' } else { Ck 'default_data_existence' $true 'unknown' 'access_denied' }
    if ($defCredS.state -eq 'ok') { Ck 'default_credentials_existence' $true 'pass' 'read' } else { Ck 'default_credentials_existence' $true 'unknown' 'access_denied' }
    $dataS = PathExistence $data 'kindergarten.db'
    $credS = PathExistence $cred ''
    if (-not [string]::IsNullOrWhiteSpace($data)) {
        $isoOk = $true; $isoDetail = 'ok'
        if ((Within $data $extract) -or (Within $extract $data)) { $isoOk = $false; $isoDetail = 'inside_package' }
        if (-not [string]::IsNullOrWhiteSpace($cred) -and ((Within $data $cred) -or (Within $cred $data))) { $isoOk = $false; $isoDetail = 'overlaps_credentials' }
        if (-not [string]::IsNullOrWhiteSpace($defData) -and [string]::Equals((Norm $data),(Norm $defData),[System.StringComparison]::OrdinalIgnoreCase)) { $isoOk = $false; $isoDetail = 'default_data_root' }
        if ($dataS.state -ne 'ok') { Ck 'data_root_isolation' $true 'unknown' 'stat_failed' } elseif ($isoOk) { Ck 'data_root_isolation' $true 'pass' $isoDetail } else { Ck 'data_root_isolation' $true 'fail' $isoDetail }
    } else { Ck 'data_root_isolation' $false 'not_run' 'none' }
    if (-not [string]::IsNullOrWhiteSpace($cred)) {
        $cOk = $true; $cDetail = 'ok'
        if ((Within $cred $extract) -or (Within $extract $cred)) { $cOk = $false; $cDetail = 'inside_package' }
        if (-not [string]::IsNullOrWhiteSpace($data) -and ((Within $cred $data) -or (Within $data $cred))) { $cOk = $false; $cDetail = 'overlaps_data' }
        if (-not [string]::IsNullOrWhiteSpace($defCred) -and [string]::Equals((Norm $cred),(Norm $defCred),[System.StringComparison]::OrdinalIgnoreCase)) { $cOk = $false; $cDetail = 'default_credential_root' }
        if ($credS.state -ne 'ok') { Ck 'credential_root_isolation' $true 'unknown' 'stat_failed' } elseif ($cOk) { Ck 'credential_root_isolation' $true 'pass' $cDetail } else { Ck 'credential_root_isolation' $true 'fail' $cDetail }
    } else { Ck 'credential_root_isolation' $false 'not_run' 'none' }
    $motwArchive = 'not_run'; $motwExe = 'not_run'
    if ($as.is_file) { $motwArchive = MotwState $archive }
    if ($exeS.is_file) { $motwExe = MotwState $exeF }
    $mstA = 'not_run'; if ($motwArchive -eq 'present' -or $motwArchive -eq 'absent') { $mstA = 'pass' } elseif ($motwArchive -eq 'unknown') { $mstA = 'unknown' }
    Ck 'motw_archive' $false $mstA $motwArchive
    $mstE = 'not_run'; if ($motwExe -eq 'present' -or $motwExe -eq 'absent') { $mstE = 'pass' } elseif ($motwExe -eq 'unknown') { $mstE = 'unknown' }
    Ck 'motw_exe' $false $mstE $motwExe
    $missing = New-Object System.Collections.ArrayList
    foreach ($id in $req) { if (-not $script:Ids.Contains($id)) { [void]$missing.Add($id) } }
    if ($missing.Count -gt 0) { Ck 'check_coverage' $true 'fail' ('missing='+($missing -join ',')) } else { Ck 'check_coverage' $true 'pass' 'ok' }
    $reqChecks = @($script:Checks | Where-Object { $_.required -eq $true })
    $failCount = @($reqChecks | Where-Object { $_.status -eq 'fail' }).Count
    $incompleteCount = @($reqChecks | Where-Object { $_.status -ne 'pass' -and $_.status -ne 'fail' }).Count
    $overall = 'pass'; $exitCode = 0
    if ($failCount -gt 0) { $overall = 'fail'; $exitCode = 1 } elseif ($incompleteCount -gt 0) { $overall = 'incomplete'; $exitCode = 2 }
    $finished = [DateTime]::UtcNow
    $report = [pscustomobject][ordered]@{
        report_schema_version = 1
        tool = 'check_windows11_target.ps1'
        tool_version = '1.0'
        scope = 'self_current_machine_only'
        run_id = $runId
        started_utc = $started.ToString('o')
        finished_utc = $finished.ToString('o')
        overall = $overall
        exit_code = $exitCode
        candidate = [pscustomobject][ordered]@{
            product = $script:Product
            archive_name = $script:ArchiveName
            archive_sha256_actual = $actualHash
            archive_sha256_expected = $expectedHash
            archive_sha256_match = $(if ($actualHash -ceq $expectedHash) { 'pass' } elseif ($actualHash -eq '') { 'unknown' } else { 'fail' })
            manifest_package = $mPkg
            manifest_build_id = $mBuild
            manifest_database_revision = $mRev
            manifest_source_freeze_digest = $mFreeze
            manifest_generated_at = $mGen
            manifest_file_count = $fileCount
            manifest_total_bytes = $totalBytes
            product_directory_count = $(if ($null -ne $tree) { $tree.dirs } else { 0 })
            product_file_count = $(if ($null -ne $tree) { $tree.files.Count } else { 0 })
            main_exe_pe_machine = $peLabel
            main_exe_signature_status = $sig.status
            main_exe_signature_integrity = $sig.integrity
            pe_signatures = @($pe.list)
            pe_signature_counts = [pscustomobject][ordered]@{ total=$pe.total; not_signed=$pe.not_signed; valid=$pe.valid; other=$pe.other; bad=$pe.bad; unknown=$pe.unknown }
            package_info_package = $(if ($null -ne $info) { [string]$info.package } else { '' })
            package_info_version = $(if ($null -ne $info) { [string]$info.version } else { '' })
            package_info_build_id = $(if ($null -ne $info) { [string]$info.build_id } else { '' })
            package_info_database_revision = $(if ($null -ne $info) { [string]$info.database_revision } else { '' })
            package_info_source_commit = $(if ($null -ne $info) { [string]$info.source_commit } else { '' })
            package_info_frontend_digest = $(if ($null -ne $info) { [string]$info.frontend_digest } else { '' })
            package_info_frontend_file_count = $(if ($null -ne $info) { [long]$info.frontend_file_count } else { 0 })
            package_info_unsigned_internal_test = $(if ($null -ne $info -and $info.unsigned_internal_test -is [bool]) { [bool]$info.unsigned_internal_test } else { $false })
        }
        environment = [pscustomobject][ordered]@{
            os_product_name = $osName
            os_build = $build
            os_build_source = $buildSrc
            os_ubr = $ubr
            os_display_version = $disp
            os_edition_id = $edition
            os_is_windows11 = ($build -ge 22000)
            os_architecture = $osArch
            os_architecture_source = $osArchSource
            native_processor_codes = $osCodes
            process_architecture = $procArch
            process_architecture_wow64 = $wow
            powershell_version = $psv
            powershell_edition = $psEd
            execution_policy = $execPolicy
            is_admin = $admin
            webview2_state = $wv.state
            webview2_version = $wv.version
            webview2_source = $wv.source
            webview2_detail = $wv.detail
            sac_state = $sac.label
            sac_number = $sac.number
            wdac_policy_count = $wdac.count
            default_data_exists = $defDataS.exists
            default_data_is_reparse = $defDataS.reparse
            default_data_has_db = $defDataS.has_db
            default_credentials_exists = $defCredS.exists
            default_credentials_is_reparse = $defCredS.reparse
            data_root_provided = (-not [string]::IsNullOrWhiteSpace($data))
            data_root_exists = $dataS.exists
            data_root_is_reparse = $dataS.reparse
            data_root_has_db = $dataS.has_db
            credential_root_provided = (-not [string]::IsNullOrWhiteSpace($cred))
            credential_root_exists = $credS.exists
            credential_root_is_reparse = $credS.reparse
            motw_archive = $motwArchive
            motw_exe = $motwExe
        }
        checks = @($script:Checks | ForEach-Object { [pscustomobject][ordered]@{ id=$_.id; required=$_.required; status=$_.status; detail=$_.detail } })
        required_failures = @($reqChecks | Where-Object { $_.status -eq 'fail' } | ForEach-Object { $_.id })
        required_unknowns = @($reqChecks | Where-Object { $_.status -ne 'pass' -and $_.status -ne 'fail' } | ForEach-Object { $_.id })
        limitations = @(
            'Read-only point-in-time check; not a security boundary and does not launch the application.',
            'Signature status is reported, not a trust or execution guarantee.',
            'NotSigned is an inventory state, not proof that policy permits execution.',
            'PE signature inventory covers actual .exe/.dll/.pyd files; other files are not treated as PE.',
            'SAC and WDAC presence is reported, not an execution guarantee.',
            'Main executable PE architecture is checked; other binaries rely on the static verifier.',
            'Hardlink aliases are not independently detected; reparse points are rejected.',
            'Alternate data streams on the extracted tree are not enumerated; the archive static verifier is authoritative.',
            'Duplicate JSON keys are delegated to the static verifier; the outer archive SHA binds the approved manifest.',
            'No target-machine execution result is implied by this report.'
        )
    }
    $reportWritten = $false
    if ($reportReq) {
        try {
            $json = $report | ConvertTo-Json -Depth 12
            WriteReport $reportFull $json
            $reportWritten = $true
            Ck 'report_written' $true 'pass' 'atomic'
        } catch {
            Ck 'report_written' $true 'unknown' 'write_failed'
            $exitCode = 2; $overall = 'incomplete'
        }
    }    Write-Host 'KGNext-E14 Windows 11 target preflight (read-only; self current machine only)'
    Write-Host ('OS: build='+[string]$build+' arch='+$osArch+' powershell='+$psv+' ('+$psEd+')')
    Write-Host ('WebView2: '+$wv.state+' '+$wv.version+' SAC: '+$sac.label+' WDAC policies: '+[string]$wdac.count)
    foreach ($c in $script:Checks) {
        $tag = 'INFO'
        if ($c.required -eq $true) { $tag = 'REQ ' }
        Write-Host (('[{0}] {1,-34} {2,-8} {3}' -f $tag,$c.id,$c.status,$c.detail))
    }
    Write-Host ('OVERALL='+$overall+' EXIT_CODE='+[string]$exitCode+' FAIL='+[string]$failCount+' INCOMPLETE='+[string]$incompleteCount)
    if ($reportReq) { if ($reportWritten) { Write-Host 'REPORT=written (path intentionally not printed)' } else { Write-Host 'REPORT=not_written' } } else { Write-Host 'REPORT=not_requested' }
    return $exitCode
}
try {
    exit (Main)
} catch {
    $m = [string]$_.Exception.Message
    if ($m -match '^[a-z0-9_]+$') { Write-Host ('ERROR='+$m) } else { Write-Host 'ERROR=unexpected_failure' }
    exit 2
}