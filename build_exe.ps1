# Build drill_cone_app.exe with PyInstaller
# Run from the project root: .\build_exe.ps1

$venv = ".\.venv\Scripts"
$script = "drill_cone_app.py"
$name = "DrillConeGenerator"

& "$venv\pyinstaller.exe" `
    --onefile `
    --windowed `
    --name $name `
    --clean `
    $script

Write-Host ""
Write-Host "Build complete. EXE is at: dist\$name.exe"
