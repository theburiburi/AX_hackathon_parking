param(
    [ValidateSet('parking', 'vision', 'frontend', 'init', 'test')]
    [string]$Service = 'parking'
)
$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
$webPython = Join-Path $PSScriptRoot '../.venv/Scripts/python.exe'
Push-Location $PSScriptRoot
try {
    if ($Service -ne 'frontend' -and -not (Test-Path -LiteralPath $webPython)) {
        throw 'Create AX_Parking/.venv and install web/requirements.txt in that environment first.'
    }
    switch ($Service) {
        'init' { & $webPython backend/seed.py }
        'parking' { & $webPython backend/manage.py runserver 127.0.0.1:8000 }
        'vision' { & $webPython -m uvicorn vision.main:app --app-dir backend --host 127.0.0.1 --port 8001 --reload --reload-dir backend/vision }
        'frontend' {
            Push-Location frontend
            try { & npm.cmd run dev } finally { Pop-Location }
        }
        'test' {
            & $webPython backend/manage.py test tracking
            if ($LASTEXITCODE -ne 0) { throw 'Parking tests failed.' }
            & $webPython -m unittest discover -s tests -v
            if ($LASTEXITCODE -ne 0) { throw 'Vision tests failed.' }
            Push-Location frontend
            try { & npm.cmd test } finally { Pop-Location }
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "Service exited with code $LASTEXITCODE" }
} finally { Pop-Location }
