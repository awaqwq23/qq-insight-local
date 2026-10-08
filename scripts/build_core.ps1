param(
    [string]$Python = "py",
    [string]$Output = "build/core"
)

$ErrorActionPreference = "Stop"
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$taskOutput = Join-Path $taskRoot $Output
$taskWork = Join-Path $taskRoot "build/pyinstaller-work"
$taskSpec = Join-Path $taskRoot "build/pyinstaller-spec"
New-Item -ItemType Directory -Force -Path $taskOutput,$taskWork,$taskSpec | Out-Null
$taskPythonArgs = @()
if ((Split-Path -Leaf $Python).ToLowerInvariant() -eq "py.exe" -or $Python -eq "py") { $taskPythonArgs += "-3.14" }
& $Python @taskPythonArgs -m PyInstaller --noconfirm --clean --onefile --name qq-insight-core --paths (Join-Path $taskRoot "src/core") --distpath $taskOutput --workpath $taskWork --specpath $taskSpec (Join-Path $taskRoot "src/core/assistant_core.py")
if ($LASTEXITCODE -ne 0) { throw "Core build failed: $LASTEXITCODE" }
if (-not (Test-Path -LiteralPath (Join-Path $taskOutput "qq-insight-core.exe"))) { throw "Core executable was not produced." }
