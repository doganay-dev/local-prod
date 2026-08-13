[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function New-RandomSecret {
    param([int]$ByteCount = 32)

    $bytes = [byte[]]::new($ByteCount)
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($bytes)
}

Write-Output ('N8N_ENCRYPTION_KEY=' + (New-RandomSecret -ByteCount 48))
Write-Output ('GATEWAY_ADMIN_TOKEN=' + (New-RandomSecret -ByteCount 32))
