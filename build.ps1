param()
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed --name Tai-Hindsight-Migrator --collect-all customtkinter --collect-all tzdata --add-data ((Join-Path $projectRoot 'migrator\fixtures') + ';migrator/fixtures') --distpath (Join-Path $projectRoot 'dist') --workpath (Join-Path $projectRoot 'build') --specpath (Join-Path $projectRoot 'build') launcher.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
    Write-Output (Join-Path $projectRoot 'dist\Tai-Hindsight-Migrator.exe')
} finally {
    Pop-Location
}
