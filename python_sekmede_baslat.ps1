param(
    [Parameter(Mandatory = $true)][string]$ScriptPath,
    [Parameter(Mandatory = $true)][string]$MarkerPath
)

$ScriptPath = [System.IO.Path]::GetFullPath($ScriptPath)
$ScriptDirectory = [System.IO.Path]::GetDirectoryName($ScriptPath)
Set-Location -LiteralPath $ScriptDirectory
try {
    & python $ScriptPath
    $ExitCode = $LASTEXITCODE
}
finally {
    New-Item -ItemType File -Path $MarkerPath -Force | Out-Null
}
exit $ExitCode
