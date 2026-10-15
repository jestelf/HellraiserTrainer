$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$work = Join-Path $env:TEMP 'HellraiserTrainerBuild'
python -m PyInstaller --noconfirm --clean --onefile --windowed --name HellraiserTrainer `
  --icon "$root\assets\Hellraiser.ico" `
  --add-data "$root\assets\Hellraiser.ico;assets" --add-data "$root\assets\enabled.wav;assets" --add-data "$root\assets\disabled.wav;assets" `
  --version-file "$root\version.txt" `
  --paths "$root\src" --distpath "$root\dist" --workpath $work --specpath $work `
  "$root\src\app.py"
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Get-Item "$root\dist\HellraiserTrainer.exe" | Select-Object Name, Length, LastWriteTime
