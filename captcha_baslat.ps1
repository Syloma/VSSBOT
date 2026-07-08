$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$CaptchaDir = Join-Path $ScriptRoot 'captcha_bot'
$MarkerPath = Join-Path $ScriptRoot 'noname_tamamlandi.tmp'
Set-Location -LiteralPath $CaptchaDir
try {
    python .\noname.py
}
finally {
    New-Item -ItemType File -Path $MarkerPath -Force | Out-Null
}
