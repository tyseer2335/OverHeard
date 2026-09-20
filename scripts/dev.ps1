$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$nodeDirectory = Get-ChildItem -LiteralPath "$projectRoot\.tools" -Directory -Filter 'node-v*-win-x64' |
    Sort-Object Name -Descending |
    Select-Object -First 1

if (-not $nodeDirectory) {
    throw 'Local Node.js was not found in .tools.'
}

$env:Path = "$($nodeDirectory.FullName);$env:Path"
$python = "$projectRoot\.venv\Scripts\python.exe"
$npm = "$($nodeDirectory.FullName)\npm.cmd"

$backend = Start-Process `
    -FilePath $python `
    -ArgumentList '-m', 'uvicorn', 'product_voice.api:app', '--reload', '--port', '8000' `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

try {
    Set-Location -LiteralPath "$projectRoot\frontend"
    Write-Host 'Product Voice is starting at http://localhost:3000' -ForegroundColor Cyan
    & $npm run dev
}
finally {
    if (-not $backend.HasExited) {
        Stop-Process -Id $backend.Id
    }
}
