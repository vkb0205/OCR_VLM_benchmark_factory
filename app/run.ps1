param([Parameter(Mandatory=$true)][string]$RunFolder)
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $Root 'OCR_VLM_benchmark_factory/.venv/Scripts/python.exe'
$env:GT_RUN = (Resolve-Path -LiteralPath $RunFolder).Path
& $Python -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
& $Python (Join-Path $PSScriptRoot 'generate_api.py')
Push-Location (Join-Path $PSScriptRoot 'web')
try {
 if (!(Test-Path node_modules)) { npm install; if ($LASTEXITCODE) { throw 'npm install failed' } }
 npm run generate
 if ($LASTEXITCODE) { throw 'Client generation failed' }
 npm run typecheck
 if ($LASTEXITCODE) { throw 'Type checking failed' }
 npm run build
 if ($LASTEXITCODE) { throw 'Web build failed' }
} finally { Pop-Location }
Push-Location $Root
try { & $Python -m uvicorn app.server.main:app --host 127.0.0.1 --port 8765 } finally { Pop-Location }
