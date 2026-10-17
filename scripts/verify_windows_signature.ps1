param(
    [Parameter(Mandatory=$true)][string]$SignedDirectory,
    [Parameter(Mandatory=$true)][ValidateSet('test-signing', 'release-signing')][string]$Policy,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$signed = Join-Path $SignedDirectory 'TiktokStreamKeyGenerator.exe'
if (-not (Test-Path $signed)) { throw 'SignPath did not return the expected EXE.' }
Write-Host "Checking signed executable with policy: $Policy"
if ($Policy -eq 'test-signing') {
    & python (Join-Path $PSScriptRoot 'verify_test_signature.py') $signed
    if ($LASTEXITCODE -ne 0) { throw "Test signature verifier failed with exit code $LASTEXITCODE." }
}
else {
    $signature = Get-AuthenticodeSignature -FilePath $signed
    if (-not $signature.SignerCertificate) { throw 'The returned EXE has no signing certificate.' }
    $expected = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
        (Join-Path $PSScriptRoot '../.signpath/test-certificate-2026.cer'))
    if ([Convert]::ToBase64String($signature.SignerCertificate.RawData) -ceq
        [Convert]::ToBase64String($expected.RawData)) {
        throw 'A test certificate cannot be used for a production release.'
    }
    if ([string]$signature.Status -ne 'Valid') {
        throw "Authenticode verification failed: $($signature.Status) $($signature.StatusMessage)"
    }
    Write-Host "Authenticode: $($signature.Status); signer: $($signature.SignerCertificate.Subject)"
}
if (-not $VerifyOnly) {
    Copy-Item $signed 'build/TiktokStreamKeyGenerator.dist/TiktokStreamKeyGenerator.exe' -Force
}
