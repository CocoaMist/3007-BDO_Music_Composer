param(
    [string]$Python = "",
    [string]$Constraints = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}
$Requirements = Join-Path $ProjectRoot "requirements-transcription.txt"
if ([string]::IsNullOrWhiteSpace($Constraints)) {
    $Constraints = Join-Path $ProjectRoot "constraints-windows-py312.txt"
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing Python interpreter: $Python"
}
if (-not (Test-Path -LiteralPath $Constraints)) {
    throw "Missing dependency constraints: $Constraints"
}

function Invoke-Pip {
    param([string[]]$PipArgs)
    & $Python -m pip @PipArgs
    if ($LASTEXITCODE -ne 0) {
        throw "pip failed with exit code $LASTEXITCODE"
    }
}

Invoke-Pip -PipArgs @(
    "install", "--constraint", $Constraints, "--upgrade", "pip", "setuptools<81"
)
# Basic Pitch 0.4.0 still declares an unavailable TensorFlow dependency on
# Python 3.12. This application deliberately uses only its ONNX backend.
Invoke-Pip -PipArgs @(
    "install", "--constraint", $Constraints, "--no-deps", "basic-pitch==0.4.0"
)
Invoke-Pip -PipArgs @(
    "install", "--constraint", $Constraints, "-r", $Requirements
)

& $Python -c "from pathlib import Path; import basic_pitch, onnxruntime, soundfile, soxr; model = Path(basic_pitch.build_icassp_2022_model_path(basic_pitch.FilenameSuffix.onnx)); assert basic_pitch.ONNX_PRESENT and model.is_file() and 'CPUExecutionProvider' in onnxruntime.get_available_providers() and soundfile.available_formats() and callable(soxr.ResampleStream)"
if ($LASTEXITCODE -ne 0) {
    throw "Transcription runtime validation failed with exit code $LASTEXITCODE"
}
Write-Host "Transcription runtime ready (Basic Pitch ONNX / CPU)."
