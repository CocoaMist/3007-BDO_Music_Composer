$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Spec = Join-Path $PSScriptRoot "BDOMusicComposer.spec"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing virtual environment: $Python"
}

Push-Location $ProjectRoot
try {
    Write-Host "Building Standard edition (optional transcription runtime excluded)."
    & $Python -m PyInstaller --noconfirm --clean --distpath dist --workpath build $Spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    Write-Host "Built: $(Join-Path $ProjectRoot 'dist\BDO-Music-Composer.exe')"
}
finally {
    Pop-Location
}
