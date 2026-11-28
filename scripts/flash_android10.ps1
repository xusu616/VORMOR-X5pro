[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
)

# Optional PowerShell entry point; all actual device commands remain native ADB.
# Use python/py directly to supply a non-default Python executable.
$ErrorActionPreference = 'Stop'
$python = Get-Command python -ErrorAction Stop
& $python.Source (Join-Path $PSScriptRoot 'flash_android10.py') @Arguments
exit $LASTEXITCODE
