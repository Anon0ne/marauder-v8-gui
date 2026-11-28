; specter-v8.nsi — NSIS installer for the Specter V8 Control desktop app.
;
; Wraps the single-file PyInstaller executable (dist\MarauderV8-Control.exe)
; into a conventional Windows Setup.exe: installs per-machine into Program
; Files, creates Start Menu and Desktop shortcuts, registers an uninstaller
; in Add/Remove Programs, and ships a matching uninstaller.
;
; The PyInstaller exe is self-contained (bundles the Python runtime, esptool
; and the portal templates), so the installer only needs that one file.
;
; Build (on Windows or with makensis on Linux, once the Windows .exe exists):
;   makensis -DVERSION=0.4.4-beta.1 -DSRCEXE=dist\MarauderV8-Control.exe packaging\windows\specter-v8.nsi
; Produces: dist\Specter-V8-Control-Setup-<VERSION>.exe

!ifndef VERSION
  !define VERSION "0.0.0-dev"
!endif
!ifndef SRCEXE
  !define SRCEXE "dist\MarauderV8-Control.exe"
!endif
!ifndef OUTFILE
  !define OUTFILE "dist\Specter-V8-Control-Setup-${VERSION}.exe"
!endif

!define APPNAME       "Specter V8 Control"
!define COMPANY       "Anon0ne"
!define APPEXE        "MarauderV8-Control.exe"
!define UNINSTKEY     "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpecterV8Control"
!define HOMEPAGE      "https://github.com/Anon0ne/marauder-v8-gui"

Name "${APPNAME} ${VERSION}"
OutFile "${OUTFILE}"
Unicode true
InstallDir "$PROGRAMFILES64\Specter V8"
InstallDirRegKey HKLM "Software\SpecterV8Control" "InstallDir"
RequestExecutionLevel admin   ; per-machine install into Program Files
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "FileFunc.nsh"   ; provides ${GetSize}
!define MUI_ICON   "..\..\marauder.ico"
!define MUI_UNICON "..\..\marauder.ico"
!define MUI_ABORTWARNING

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APPEXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Launch ${APPNAME}"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Install"
  SetOutPath "$INSTDIR"
  File "/oname=${APPEXE}" "${SRCEXE}"

  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut  "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\${APPEXE}" "" "$INSTDIR\${APPEXE}" 0
  CreateShortcut  "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" "$INSTDIR\uninstall.exe"
  CreateShortcut  "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${APPEXE}" "" "$INSTDIR\${APPEXE}" 0

  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "Software\SpecterV8Control" "InstallDir" "$INSTDIR"

  ; Add/Remove Programs registration.
  WriteRegStr   HKLM "${UNINSTKEY}" "DisplayName"     "${APPNAME}"
  WriteRegStr   HKLM "${UNINSTKEY}" "DisplayVersion"  "${VERSION}"
  WriteRegStr   HKLM "${UNINSTKEY}" "Publisher"       "${COMPANY}"
  WriteRegStr   HKLM "${UNINSTKEY}" "DisplayIcon"     "$INSTDIR\${APPEXE}"
  WriteRegStr   HKLM "${UNINSTKEY}" "URLInfoAbout"    "${HOMEPAGE}"
  WriteRegStr   HKLM "${UNINSTKEY}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegStr   HKLM "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoRepair" 1

  ; Report the installed footprint to Add/Remove Programs (KB).
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${UNINSTKEY}" "EstimatedSize" $0
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\${APPEXE}"
  Delete "$INSTDIR\uninstall.exe"
  RMDir  "$INSTDIR"

  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk"
  RMDir  "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\${APPNAME}.lnk"

  DeleteRegKey HKLM "${UNINSTKEY}"
  DeleteRegKey HKLM "Software\SpecterV8Control"
SectionEnd
