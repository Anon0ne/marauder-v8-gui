param([switch]$EnableNPU, [string]$PythonExe)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = $PythonExe
if (!$python) {
  $python = & py -3.12 -c 'import sys; print(sys.executable)'
  if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12.10 x64 first, or pass -PythonExe.' }
}
& $python -c 'import sys; assert sys.version_info[:3] == (3,12,10), sys.version'
if ($LASTEXITCODE -ne 0) { throw 'The audited build requires Python 3.12.10.' }
$buildEnvironment = Join-Path $PSScriptRoot ('.build-venv-' + [guid]::NewGuid().ToString('N'))
& $python -m venv $buildEnvironment
if ($LASTEXITCODE -ne 0) { throw 'Build environment creation failed.' }
$buildPython = Join-Path $buildEnvironment 'Scripts\python.exe'
$lock = if ($EnableNPU) { 'requirements-npu-build.lock' } else { 'requirements-build.lock' }
& $buildPython -m pip install -r $lock
if ($LASTEXITCODE -ne 0) { throw 'Pinned dependency installation failed.' }
& $buildPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed.' }
& $buildPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Regression tests failed; build stopped.' }
& $buildPython -m PyInstaller --noconfirm --clean MarauderV8-Control.spec
if ($LASTEXITCODE -ne 0) { throw 'Standalone build failed.' }
Get-FileHash -Algorithm SHA256 -LiteralPath 'dist\MarauderV8-Control.exe'
