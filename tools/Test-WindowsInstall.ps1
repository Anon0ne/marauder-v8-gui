param([Parameter(Mandatory=$true)][string]$TestRoot)
$ErrorActionPreference='Stop'
$repo=Split-Path $PSScriptRoot -Parent
$exe=Join-Path $repo 'dist\MarauderV8-Control.exe'
$reports=Join-Path $repo 'dist\windows-verification'
New-Item -ItemType Directory -Path $reports -Force | Out-Null
$expected=(Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash
function Test-InstalledApp([string]$Root,[string]$Label) {
  $installed=Join-Path $Root 'App\MarauderV8-Control.exe'
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $installed).Hash -ne $expected) { throw "$Label install checksum mismatch" }
  $wsh=New-Object -ComObject WScript.Shell
  foreach ($dir in @('Desktop','Start Menu')) {
    $path=Join-Path $Root "$dir\Marauder V8 Control.lnk"
    if (!(Test-Path -LiteralPath $path)) { throw "Missing shortcut: $path" }
    $link=$wsh.CreateShortcut($path)
    if ($link.TargetPath -ne $installed -or $link.WorkingDirectory -ne (Split-Path $installed)) { throw "Incorrect shortcut: $path" }
  }
  $report=Join-Path $reports "$Label.json"
  $argsList=@('--no-autoconnect','--smoke-test',('"{0}"' -f $report))
  $process=Start-Process -FilePath $installed -ArgumentList $argsList -WorkingDirectory (Split-Path $installed) -PassThru
  if (!$process.WaitForExit(60000)) { $process.Kill();throw "$Label executable did not finish smoke test" }
  if ($process.ExitCode -ne 0 -or !(Test-Path -LiteralPath $report)) { throw "$Label packaged GUI failed, exit $($process.ExitCode)" }
  $result=Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
  if ($result.result -ne 'pass' -or !$result.frozen -or $result.connected -or $result.autoconnect) { throw "$Label packaged GUI verification failed" }
  if ($result.pro_plugin_loaded) { throw 'Public test package unexpectedly includes the private Pro add-on' }
  Write-Host "${Label}: checksums, shortcuts and packaged GUI pages passed."
}
Test-InstalledApp (Join-Path $TestRoot 'Source Install') 'source-install'
$package=Join-Path $TestRoot 'Portable Package'
New-Item -ItemType Directory -Path $package -Force | Out-Null
foreach ($file in @('Install-Windows.ps1','INSTALL_WINDOWS.cmd','WINDOWS_INSTALL.txt')) { Copy-Item -LiteralPath (Join-Path $repo $file) -Destination $package }
Copy-Item -LiteralPath $exe -Destination $package
("$($expected.ToLower())  MarauderV8-Control.exe") | Set-Content -LiteralPath (Join-Path $package 'SHA256SUMS.txt') -Encoding ascii
$portable=Join-Path $TestRoot 'Portable Install'
& (Join-Path $package 'Install-Windows.ps1') -InstallDirectory (Join-Path $portable 'App') -DesktopDirectory (Join-Path $portable 'Desktop') -StartMenuDirectory (Join-Path $portable 'Start Menu')
Test-InstalledApp $portable 'portable-install'
Copy-Item -LiteralPath $reports -Destination (Join-Path $package 'verification') -Recurse -Force
Copy-Item -LiteralPath $package -Destination (Join-Path $repo 'dist\Windows-Test') -Recurse -Force
Compress-Archive -Path (Join-Path $package '*') -DestinationPath (Join-Path $repo 'dist\Specter-Windows-Test.zip') -Force
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $repo 'dist\Specter-Windows-Test.zip') | Format-List
