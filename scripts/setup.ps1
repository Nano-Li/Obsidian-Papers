$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment' }
}
& .venv/Scripts/python.exe -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
$engineRoot = Join-Path $projectRoot '_references/ref-downloader'
$engineCommit = '1cc667351875410197acf4471e667ac272a0092e'
if (-not (Test-Path -LiteralPath $engineRoot)) {
    git clone https://github.com/ltczding-gif/ref-downloader.git $engineRoot
    if ($LASTEXITCODE -ne 0) { throw 'Download engine clone failed' }
    git -C $engineRoot checkout --detach $engineCommit
    if ($LASTEXITCODE -ne 0) { throw 'Could not pin download engine' }
}
$actualCommit = git -C $engineRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $actualCommit -ne $engineCommit) { throw 'Download engine revision mismatch' }
if (-not (Test-Path -LiteralPath 'config/mineru.local.toml')) {
    Copy-Item -LiteralPath 'config/mineru.example.toml' -Destination 'config/mineru.local.toml'
}
Write-Host 'Setup complete. Use .venv/Scripts/obsidian-papers.exe --help'
