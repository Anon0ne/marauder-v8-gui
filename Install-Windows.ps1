param(
  [string]$ExecutablePath = (Join-Path $PSScriptRoot 'MarauderV8-Control.exe'),
  [string]$InstallDirectory,
  [string]$DesktopDirectory,
  [string]$StartMenuDirectory
)
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne 'Win32NT') { throw 'This installer requires Windows.' }
if (!(Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) { throw "Executable not found: $ExecutablePath" }
if (!$InstallDirectory) { $InstallDirectory=Join-Path $env:LOCALAPPDATA 'Programs\MarauderV8-Control' }
if (!$DesktopDirectory) { $DesktopDirectory=[Environment]::GetFolderPath('Desktop') }
if (!$StartMenuDirectory) { $StartMenuDirectory=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs' }
$source=(Resolve-Path -LiteralPath $ExecutablePath).Path
$expected=(Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash
New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
$target=Join-Path $InstallDirectory 'MarauderV8-Control.exe'
if ([IO.Path]::GetFullPath($source) -ne [IO.Path]::GetFullPath($target)) {
  Copy-Item -LiteralPath $source -Destination $target -Force
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash -ne $expected) { throw 'Installed executable checksum mismatch.' }
$wsh=New-Object -ComObject WScript.Shell
foreach ($dir in @($DesktopDirectory,$StartMenuDirectory)) {
  New-Item -ItemType Directory -Path $dir -Force | Out-Null
  $link=$wsh.CreateShortcut((Join-Path $dir 'Marauder V8 Control.lnk'))
  $link.TargetPath=$target
  $link.WorkingDirectory=$InstallDirectory
  $link.Description='Marauder V8 Control - Specter validation build'
  $link.IconLocation=$target
  $link.Save()
}
Write-Host "Installed: $target"
Write-Host "SHA256: $expected"
Write-Host 'Desktop and Start Menu shortcuts created. No Python is required for this packaged EXE.'
