param(
    [string]$Configuration = "Release",
    [switch]$AddressSanitizer
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$source = Join-Path $repoRoot "src\bdo_music_composer\audio\bdo_native_audio_core.cpp"
$output = Join-Path $repoRoot "src\bdo_music_composer\audio\bdo_native_audio_core.dll"
$buildDir = Join-Path $repoRoot "build\native_audio"
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$builtName = if ($AddressSanitizer) { "bdo_native_audio_core_asan.dll" } else { "bdo_native_audio_core.dll" }
$builtDll = Join-Path $buildDir $builtName
$object = Join-Path $buildDir "bdo_native_audio_core.obj"
$pdb = Join-Path $buildDir "bdo_native_audio_core.pdb"
$importLibrary = Join-Path $buildDir "bdo_native_audio_core.lib"
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    throw "Visual Studio Installer vswhere.exe was not found"
}
$installation = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installation) {
    throw "Visual C++ x64 build tools are required"
}
$devcmd = Join-Path $installation "Common7\Tools\VsDevCmd.bat"
$optimisation = if ($Configuration -eq "Debug") { "/Od /Zi" } else { "/O2 /DNDEBUG" }
$sanitizer = if ($AddressSanitizer) { "/fsanitize=address /Zi" } else { "" }
$compile = "cl /nologo /std:c++20 /EHsc /LD $optimisation $sanitizer /W4 /permissive- /Fo:`"$object`" /Fd:`"$pdb`" `"$source`" /link /OUT:`"$builtDll`" /IMPLIB:`"$importLibrary`""
$command = "`"$devcmd`" -arch=x64 -host_arch=x64 >nul && $compile"
& cmd.exe /d /s /c $command
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $builtDll)) {
    throw "native audio core build failed"
}
if (-not $AddressSanitizer) {
    Copy-Item -Force -LiteralPath $builtDll -Destination $output
    Write-Output $output
}
else {
    Write-Output $builtDll
}
