$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Error 'Backend environment not found. Run: backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt'
    exit 1
}

& $python -m uvicorn app.main:app --app-dir (Join-Path $root 'backend') --host 0.0.0.0 --port 8000 --reload