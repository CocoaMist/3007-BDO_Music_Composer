param(
    [Parameter(Mandatory = $true)]
    [string]$Artifact,
    [string]$CertificateThumbprint = "",
    [string]$TimestampUrl = "http://timestamp.acs.microsoft.com"
)

$ErrorActionPreference = "Stop"
$resolvedArtifact = (Resolve-Path -LiteralPath $Artifact).Path
$signTool = Get-ChildItem -Path "${env:ProgramFiles(x86)}\Windows Kits\10\bin" `
    -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "\\x64\\signtool\.exe$" } |
    Sort-Object FullName -Descending |
    Select-Object -First 1
if (-not $signTool) {
    throw "Windows SDK SignTool was not found"
}
if ($CertificateThumbprint) {
    & $signTool.FullName sign /sha1 $CertificateThumbprint /fd SHA256 `
        /tr $TimestampUrl /td SHA256 $resolvedArtifact
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode signing failed with exit code $LASTEXITCODE"
    }
}
& $signTool.FullName verify /pa /all /v $resolvedArtifact
if ($LASTEXITCODE -ne 0) {
    throw "Authenticode verification failed with exit code $LASTEXITCODE"
}
$signature = Get-AuthenticodeSignature -LiteralPath $resolvedArtifact
if ($signature.Status -ne "Valid") {
    throw "Authenticode status is $($signature.Status), expected Valid"
}
Write-Output "Verified Authenticode publisher: $($signature.SignerCertificate.Subject)"
