param(
    [Parameter(Mandatory=$true)][string]$SignedDirectory,
    [Parameter(Mandatory=$true)][ValidateSet('test-signing', 'release-signing')][string]$Policy
)
$ErrorActionPreference = 'Stop'
$verifier = Join-Path $PSScriptRoot 'verify_windows_signature.ps1'
$signed = Join-Path (Resolve-Path $SignedDirectory).Path 'TiktokStreamKeyGenerator.exe'
$expected = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
    (Join-Path $PSScriptRoot '../.signpath/test-certificate-2026.cer'))
function Get-TestRootCount {
    $store = [System.Security.Cryptography.X509Certificates.X509Store]::new('Root', 'CurrentUser')
    try {
        $store.Open('ReadOnly')
        return $store.Certificates.Find('FindByThumbprint', $expected.Thumbprint, $false).Count
    }
    finally { $store.Dispose() }
}
$initialRoots = Get-TestRootCount
$temp = Join-Path ([IO.Path]::GetTempPath()) ('signpath-integrity-' + [Guid]::NewGuid())
[void](New-Item -ItemType Directory $temp)
try {
    Write-Host 'Checking the original signed executable is accepted.'
    & $verifier -SignedDirectory $SignedDirectory -Policy $Policy -VerifyOnly
    if ((Get-TestRootCount) -ne $initialRoots) { throw 'Verification left a test root certificate installed.' }

    # Alter a byte in the first PE section, preserving the embedded signature
    # and certificate so this exercises file integrity rather than parsing.
    $bytes = [IO.File]::ReadAllBytes($signed)
    $pe = [BitConverter]::ToInt32($bytes, 0x3c)
    $section = $pe + 24 + [BitConverter]::ToUInt16($bytes, $pe + 20)
    $offset = [BitConverter]::ToUInt32($bytes, $section + 20)
    $bytes[$offset] = $bytes[$offset] -bxor 1
    $tampered = Join-Path $temp 'TiktokStreamKeyGenerator.exe'
    [IO.File]::WriteAllBytes($tampered, $bytes)
    if ([string](Get-AuthenticodeSignature $tampered).Status -ne 'HashMismatch') {
        throw 'The test did not produce a detectable executable hash mismatch.'
    }
    $rejected = $false
    Write-Host 'Checking a changed PE section is rejected.'
    try { & $verifier -SignedDirectory $temp -Policy $Policy -VerifyOnly }
    catch { $rejected = $true }
    if (-not $rejected) { throw 'The verifier accepted a modified executable.' }
    if ((Get-TestRootCount) -ne $initialRoots) { throw 'Failed verification left a test root installed.' }

    if ($Policy -eq 'test-signing') {
        Write-Host 'Checking the test certificate is rejected for production.'
        $rejected = $false
        try { & $verifier -SignedDirectory $SignedDirectory -Policy release-signing -VerifyOnly }
        catch { $rejected = $true }
        if (-not $rejected) { throw 'The verifier accepted a test certificate for production.' }
    }
    Write-Host 'Signature checks passed: valid artifact accepted, changed artifact rejected, trust store unchanged.'
    # GitHub's pwsh wrapper exits with the last native command's status. The
    # deliberately rejected tampered EXE must not mark this successful test red.
    $global:LASTEXITCODE = 0
}
finally { Remove-Item -LiteralPath $temp -Recurse -Force }
