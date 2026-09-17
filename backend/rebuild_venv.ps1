$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (Test-Path '.\venv\Scripts\python.exe') {
        & .\venv\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3, 12), 'Use Python 3.12'"
        if ($LASTEXITCODE -ne 0) {
            throw 'Deactivate and rename the existing venv, then rerun this script.'
        }
    } else {
        & py -3.12 -m venv venv
        if ($LASTEXITCODE -ne 0) {
            throw 'Install Python 3.12 first. See SETUP.md.'
        }
    }
    & .\venv\Scripts\python.exe -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
    & .\venv\Scripts\python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & .\venv\Scripts\python.exe -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed.' }
    Write-Host 'Dependencies ready. Run .\venv\Scripts\python.exe download_models.py to install MinerU models.'
} finally {
    Pop-Location
}
