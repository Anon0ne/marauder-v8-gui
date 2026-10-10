param([switch]$BuildOnly)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Find-Python {
  $candidates = @(
    @{Exe='py'; Args=@('-3.13')},
    @{Exe='py'; Args=@('-3.12')},
    @{Exe='py'; Args=@('-3.11')},
    @{Exe='py'; Args=@('-3.10')},
    @{Exe='py'; Args=@('-3')},
    @{Exe='python'; Args=@()},
    @{Exe=(Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'); Args=@()},
    @{Exe=(Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'); Args=@()},
    @{Exe=(Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'); Args=@()},
    @{Exe=(Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe'); Args=@()}
  )
  foreach ($candidate in $candidates) {
    $cmd=Get-Command $candidate.Exe -ErrorAction SilentlyContinue
    if (!$cmd) { continue }
    $argsList=@($candidate.Args)
    try {
      $version=& $cmd.Source @argsList -c 'import sys; print(sys.executable if (3,10) <= sys.version_info[:2] < (3,14) else str())' 2>$null
      if ($LASTEXITCODE -eq 0 -and $version -is [string] -and (Test-Path -LiteralPath $version -PathType Leaf)) {
        return [pscustomobject]@{ Exe=$version; Args=@() }
      }
    } catch { }
  }
  return $null
}
function Install-Python {
  Write-Host 'Python 3.10-3.13 not detected. Installing Python 3.12 before building...' -ForegroundColor Yellow
  $winget=Get-Command winget.exe -ErrorAction SilentlyContinue
  if ($winget) {
    & winget install --id Python.Python.3.12 --exact --source winget --scope user --accept-source-agreements --accept-package-agreements --disable-interactivity | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Warning 'winget installation failed; trying official installer.' }
  }
  $python=Find-Python
  if ($python) { return $python }
  $version='3.12.10'
  $url="https://www.python.org/ftp/python/$version/python-$version-amd64.exe"
  $installer=Join-Path $env:TEMP "python-$version-amd64.exe"
  Write-Host "Downloading official Python installer from $url"
  Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
  $signature=Get-AuthenticodeSignature -FilePath $installer
  if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
    throw 'Python installer signature verification failed. Installation stopped.'
  }
  $proc=Start-Process -FilePath $installer -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1 Include_test=0' -WindowStyle Hidden -Wait -PassThru
  if ($proc.ExitCode -notin @(0,3010)) { throw "Python installer exited with code $($proc.ExitCode)" }
  $userPython=Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
  if (Test-Path $userPython) {
    & $userPython -c 'import sys; assert (3,10) <= sys.version_info[:2] < (3,14)' | Out-Host
    if ($LASTEXITCODE -eq 0) { return [pscustomobject]@{ Exe=$userPython; Args=@() } }
  }
  $python=Find-Python
  if (!$python) { throw 'Python installed but could not be located. Reopen terminal and rerun the installer.' }
  return $python
}
$python=Find-Python
if (!$python) { $python=Install-Python }
if (!$python.Exe -or !(Test-Path -LiteralPath $python.Exe -PathType Leaf)) { throw 'Python detection did not return a valid executable.' }
Write-Host "Using Python: $($python.Exe)" -ForegroundColor Green
Write-Host 'Creating isolated build environment...'
$pythonArgs=@($python.Args)
& $python.Exe @pythonArgs -m venv .build-venv
if ($LASTEXITCODE -ne 0) { throw 'Failed to create venv' }
$py=Join-Path $PSScriptRoot '.build-venv\Scripts\python.exe'
& $py -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed' }
Write-Host 'Checking application and build dependencies...'
# pip checks installed versions against requirements and only downloads missing/outdated packages.
& $py -m pip install --prefer-binary -r requirements.txt 'pyinstaller>=6.0,<7'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; check internet access and pip output.' }
& $py -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency conflict detected; build stopped.' }
& $py -c 'import serial, esptool, PyInstaller'
if ($LASTEXITCODE -ne 0) { throw 'Required module import verification failed.' }
Write-Host 'Verified: pyserial, esptool, PyInstaller'
& $py -m PyInstaller --noconfirm --clean MarauderV8-Control.spec
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed' }
$exe=Join-Path $PSScriptRoot 'dist\MarauderV8-Control.exe'
if (!(Test-Path $exe)) { throw 'Build did not produce executable' }
Write-Host "Built: $exe"
if ($BuildOnly) { exit 0 }
$install=Join-Path $env:LOCALAPPDATA 'Programs\MarauderV8-Control'
New-Item -ItemType Directory -Path $install -Force | Out-Null
Copy-Item $exe (Join-Path $install 'MarauderV8-Control.exe') -Force
$wsh=New-Object -ComObject WScript.Shell
$desktop=[Environment]::GetFolderPath('Desktop')
$start=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
foreach ($dir in @($desktop,$start)) {
  $lnk=$wsh.CreateShortcut((Join-Path $dir 'Marauder V8 Control.lnk'))
  $lnk.TargetPath=Join-Path $install 'MarauderV8-Control.exe'
  $lnk.WorkingDirectory=$install
  $lnk.Description='Marauder V8 Control GUI'
  $lnk.IconLocation=Join-Path $install 'MarauderV8-Control.exe'
  $lnk.Save()
}
Write-Host "Installed to $install"
Write-Host 'Desktop and Start Menu shortcuts created.'
