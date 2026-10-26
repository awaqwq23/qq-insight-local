param([string]$ReleaseDirectory = (Join-Path (Split-Path $PSScriptRoot -Parent) 'release'))
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$taskDirectory = [IO.Path]::GetFullPath($ReleaseDirectory)
$taskExpected = Join-Path $taskRoot 'release'
$taskTestRoot = (Join-Path $taskRoot 'build\test-temp') + [IO.Path]::DirectorySeparatorChar
if ($taskDirectory -ne $taskExpected -and -not $taskDirectory.StartsWith($taskTestRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Release cleanup target is outside the release or test directory.' }
if (-not (Test-Path -LiteralPath $taskDirectory -PathType Container)) { throw 'Release directory does not exist.' }
$taskResolved = (Resolve-Path -LiteralPath $taskDirectory).Path
if ($taskResolved -ne $taskDirectory -or ((Get-Item -LiteralPath $taskDirectory).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Release directory cannot be a redirected path.' }
$taskFiles = @(Get-ChildItem -LiteralPath $taskDirectory -File | Where-Object { $_.Name -match '^QQ-Insight-(\d+\.\d+\.\d+)-rel-portable\.exe$' } | ForEach-Object { [pscustomobject]@{ File=$_; Version=[version]([regex]::Match($_.Name,'\d+\.\d+\.\d+').Value) } } | Sort-Object Version -Descending)
$taskPrefix = $taskDirectory + [IO.Path]::DirectorySeparatorChar
foreach ($taskOld in ($taskFiles | Select-Object -Skip 2)) {
    foreach ($taskPath in @($taskOld.File.FullName,($taskOld.File.FullName+'.sha256'))) {
        $taskAbsolute = [IO.Path]::GetFullPath($taskPath)
        if (-not $taskAbsolute.StartsWith($taskPrefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Release file escaped the verified directory.' }
        if (Test-Path -LiteralPath $taskAbsolute) {
            if ((Get-Item -LiteralPath $taskAbsolute).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Release file cannot be a link.' }
            Remove-Item -LiteralPath $taskAbsolute -Force
        }
    }
}
$taskLines = @()
foreach ($taskKept in ($taskFiles | Select-Object -First 2)) {
    $taskStream = [IO.File]::OpenRead($taskKept.File.FullName)
    $taskHasher = [Security.Cryptography.SHA256]::Create()
    try { $taskHash = [BitConverter]::ToString($taskHasher.ComputeHash($taskStream)).Replace('-','').ToLowerInvariant() }
    finally { $taskStream.Dispose(); $taskHasher.Dispose() }
    $taskLine = $taskHash+'  '+$taskKept.File.Name
    [IO.File]::WriteAllText(($taskKept.File.FullName+'.sha256'),$taskLine+"`n",[Text.UTF8Encoding]::new($false))
    $taskLines += $taskLine
    Write-Output ('Kept '+$taskKept.File.Name)
}
[IO.File]::WriteAllText((Join-Path $taskDirectory 'SHA256.txt'),(($taskLines -join "`n")+"`n"),[Text.UTF8Encoding]::new($false))
