$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if (!$python) {
    $userPythonPath = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (!(Test-Path -LiteralPath $userPythonPath)) { throw 'Install Python 3.12 before NPU setup.' }
    $pythonExe = $userPythonPath
} else { $pythonExe = $python.Source }
& $pythonExe -m venv .npu-venv
if ($LASTEXITCODE -ne 0) { throw 'NPU environment creation failed.' }
$npuPython = Join-Path $PSScriptRoot '.npu-venv\Scripts\python.exe'
& $npuPython -m pip install -r requirements.txt -r requirements-npu.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $npuPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed.' }
& $npuPython download_npu_model.py
if ($LASTEXITCODE -ne 0) { throw 'Model download failed.' }
& $npuPython marauder_npu.py --model (Join-Path $PSScriptRoot 'models\phi35-npu')
if ($LASTEXITCODE -ne 0) { throw 'NPU inference test failed. No CPU fallback was used.' }
Write-Host 'NPU ready. Launch the beta with RUN_NPU.cmd.'
