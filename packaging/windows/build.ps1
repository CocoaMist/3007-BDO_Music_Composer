param(
    [switch]$PublicRelease
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Spec = Join-Path $PSScriptRoot "BDOMusicComposer.spec"
$Policy = Join-Path $ProjectRoot "packaging\transcription_release_policy.json"
$AuditScript = Join-Path $ProjectRoot "scripts\audit_transcription_licenses.py"
$OutputExecutable = Join-Path $ProjectRoot "dist\BDO-Music-Composer.exe"
$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$LicenseOutput = Join-Path $TempRoot (
    "bdo-transcription-licenses-" + [Guid]::NewGuid().ToString("N")
)
$BuildWork = Join-Path $TempRoot (
    "bdo-music-composer-build-" + [Guid]::NewGuid().ToString("N")
)
$StartupSmokeRoot = Join-Path $TempRoot (
    "bdo-music-composer-startup-smoke-" + [Guid]::NewGuid().ToString("N")
)

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing virtual environment: $Python"
}

$PreviousLicenseDir = [Environment]::GetEnvironmentVariable(
    "BDO_TRANSCRIPTION_LICENSE_DIR",
    "Process"
)
$PreviousUserDataDir = [Environment]::GetEnvironmentVariable(
    "BDO_USER_DATA_DIR",
    "Process"
)
$PreviousQtPlatform = [Environment]::GetEnvironmentVariable(
    "QT_QPA_PLATFORM",
    "Process"
)

Push-Location $ProjectRoot
try {
    if (Test-Path -LiteralPath $OutputExecutable) {
        try {
            $OutputProbe = [IO.File]::Open(
                $OutputExecutable,
                [IO.FileMode]::Open,
                [IO.FileAccess]::ReadWrite,
                [IO.FileShare]::None
            )
            $OutputProbe.Dispose()
        }
        catch {
            throw (
                "Cannot replace $OutputExecutable. Close the running " +
                "BDO Music Composer window and try again."
            )
        }
    }

    & $Python -c @"
from pathlib import Path
import basic_pitch
import onnxruntime
import soundfile
import soxr
model = Path(basic_pitch.build_icassp_2022_model_path(basic_pitch.FilenameSuffix.onnx))
assert basic_pitch.ONNX_PRESENT
assert model.is_file()
assert 'CPUExecutionProvider' in onnxruntime.get_available_providers()
assert soundfile.available_formats()
assert callable(soxr.ResampleStream)
"@
    if ($LASTEXITCODE -ne 0) {
        throw (
            "Bundled transcription runtime is unavailable. Run " +
            "scripts\install_transcription.ps1 first."
        )
    }

    $AuditArguments = @(
        $AuditScript,
        "--output-dir",
        $LicenseOutput,
        "--policy",
        $Policy
    )
    if ($PublicRelease) {
        $AuditArguments += "--require-public-clearance"
    }
    & $Python @AuditArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Transcription license audit failed with exit code $LASTEXITCODE"
    }

    $env:BDO_TRANSCRIPTION_LICENSE_DIR = $LicenseOutput
    if ($PublicRelease) {
        Write-Host (
            "Building the reviewed BDO Music Composer release with bundled " +
            "Basic Pitch ONNX inference."
        )
    }
    else {
        Write-Warning (
            "Building the sole BDO Music Composer package for local " +
            "evaluation. The checked-in license policy does not yet " +
            "authorize public distribution."
        )
    }

    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath dist `
        --workpath $BuildWork `
        $Spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }

    $TranscriptionSelfTest = Start-Process `
        -FilePath $OutputExecutable `
        -ArgumentList "--self-test-transcription" `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($TranscriptionSelfTest.ExitCode -ne 0) {
        throw (
            "Frozen transcription self-test failed with exit code " +
            "$($TranscriptionSelfTest.ExitCode)"
        )
    }
    $env:BDO_USER_DATA_DIR = $StartupSmokeRoot
    $env:QT_QPA_PLATFORM = "offscreen"
    [IO.Directory]::CreateDirectory($StartupSmokeRoot) | Out-Null
    $StartupSelfTest = Start-Process `
        -FilePath $OutputExecutable `
        -ArgumentList "--self-test-startup" `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($StartupSelfTest.ExitCode -ne 0) {
        throw (
            "Frozen 10-second startup self-test failed with exit code " +
            "$($StartupSelfTest.ExitCode)"
        )
    }
    Write-Host "Built and verified: $OutputExecutable"
}
finally {
    Pop-Location
    if ($null -eq $PreviousLicenseDir) {
        Remove-Item Env:\BDO_TRANSCRIPTION_LICENSE_DIR `
            -ErrorAction SilentlyContinue
    }
    else {
        $env:BDO_TRANSCRIPTION_LICENSE_DIR = $PreviousLicenseDir
    }
    if ($null -eq $PreviousUserDataDir) {
        Remove-Item Env:\BDO_USER_DATA_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:BDO_USER_DATA_DIR = $PreviousUserDataDir
    }
    if ($null -eq $PreviousQtPlatform) {
        Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    }
    else {
        $env:QT_QPA_PLATFORM = $PreviousQtPlatform
    }

    if (Test-Path -LiteralPath $LicenseOutput) {
        $ResolvedLicenseOutput = [IO.Path]::GetFullPath($LicenseOutput)
        if (
            $ResolvedLicenseOutput.StartsWith(
                $TempRoot,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            (Split-Path $ResolvedLicenseOutput -Leaf).StartsWith(
                "bdo-transcription-licenses-",
                [StringComparison]::Ordinal
            )
        ) {
            Remove-Item -LiteralPath $ResolvedLicenseOutput `
                -Recurse `
                -Force
        }
    }

    if (Test-Path -LiteralPath $BuildWork) {
        $ResolvedBuildWork = [IO.Path]::GetFullPath($BuildWork)
        if (
            $ResolvedBuildWork.StartsWith(
                $TempRoot,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            (Split-Path $ResolvedBuildWork -Leaf).StartsWith(
                "bdo-music-composer-build-",
                [StringComparison]::Ordinal
            )
        ) {
            Remove-Item -LiteralPath $ResolvedBuildWork `
                -Recurse `
                -Force
        }
    }

    if (Test-Path -LiteralPath $StartupSmokeRoot) {
        $ResolvedStartupSmokeRoot = [IO.Path]::GetFullPath(
            $StartupSmokeRoot
        )
        if (
            $ResolvedStartupSmokeRoot.StartsWith(
                $TempRoot,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            (Split-Path $ResolvedStartupSmokeRoot -Leaf).StartsWith(
                "bdo-music-composer-startup-smoke-",
                [StringComparison]::Ordinal
            )
        ) {
            Remove-Item -LiteralPath $ResolvedStartupSmokeRoot `
                -Recurse `
                -Force
        }
    }
}
