$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildPython = Join-Path $ProjectRoot '.build-env\Scripts\python.exe'
if (-not (Test-Path $BuildPython)) {
    py -3.12 -m venv (Join-Path $ProjectRoot '.build-env')
}
& $BuildPython -m pip install -r (Join-Path $ProjectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Runtime dependency installation failed.' }
& $BuildPython -m pip install 'PyInstaller==6.22.3'
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }
& $BuildPython -m PyInstaller --noconfirm --clean (Join-Path $ProjectRoot 'Hearth.spec')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Write-Host 'Built dist\Hearth. Compile installer\Hearth.iss with Inno Setup 7.1.1 to create the setup package.'
