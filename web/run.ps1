param(
    [ValidateSet('app', 'prepare', 'build', 'init', 'test')]
    [string]$Service = 'app'
)
$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
$webPython = Join-Path $PSScriptRoot '../.venv/Scripts/python.exe'
Push-Location $PSScriptRoot
try {
    if ($Service -ne 'build' -and -not (Test-Path -LiteralPath $webPython)) {
        throw 'Create AX_Parking/.venv and install the root requirements.txt in that environment first.'
    }
    switch ($Service) {
        'app' { & $webPython -B run.py }
        'prepare' { & $webPython -B build_replay.py }
        'build' {
            Push-Location frontend
            try { & npm.cmd run build } finally { Pop-Location }
        }
        'init' { & $webPython backend/seed.py }
        'test' {
            & $webPython backend/manage.py test tracking
            if ($LASTEXITCODE -ne 0) { throw 'Parking tests failed.' }
            & $webPython -B -m unittest discover -s tests -v
            if ($LASTEXITCODE -ne 0) { throw 'Replay tests failed.' }
            Push-Location frontend
            try { & npm.cmd test } finally { Pop-Location }
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "Service exited with code $LASTEXITCODE" }
} finally { Pop-Location }
