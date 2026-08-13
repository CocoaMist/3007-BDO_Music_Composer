[CmdletBinding()]
param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pythonPath = Join-Path $repositoryRoot $Python
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python executable was not found: $pythonPath"
}

$outputRoot = Join-Path $repositoryRoot "out\tools\bdo-to-midi"
$workRoot = Join-Path $repositoryRoot "build\bdo-to-midi"
& $pythonPath -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "BDO-to-MIDI" `
    --paths (Join-Path $repositoryRoot "src") `
    --paths (Join-Path $repositoryRoot "tools") `
    --distpath $outputRoot `
    --workpath $workRoot `
    --specpath $workRoot `
    (Join-Path $repositoryRoot "tools\bdo_to_midi_gui.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host "Built standalone executable: $(Join-Path $outputRoot 'BDO-to-MIDI.exe')"
