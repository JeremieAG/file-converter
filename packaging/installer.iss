; Installateur Windows de File Converter (Inno Setup 6.3 ou plus récent).
; Compilé par build.bat après PyInstaller ; à la main :
;   ISCC.exe packaging\installer.iss
; La version est lue dans FileConverter.exe (elle vient de file_converter/__init__.py).

#define AppName "File Converter"
#define AppExe "FileConverter.exe"
#define AppPublisher "JeremieAG"
#define AppURL "https://github.com/JeremieAG/file-converter"
#define DistDir AddBackslash(SourcePath) + "..\dist\FileConverter"

#if !FileExists(DistDir + "\" + AppExe)
  #error "dist\FileConverter\FileConverter.exe introuvable : lancez d'abord PyInstaller (build.bat)."
#endif
#if !FileExists(DistDir + "\ffmpeg.exe")
  #error "dist\FileConverter\ffmpeg.exe introuvable : le build PyInstaller est incomplet."
#endif
#ifndef AppVersion
  #define AppVersion GetFileProductVersion(DistDir + "\" + AppExe)
#endif

[Setup]
; Identifiant stable de l'application : ne pas changer (sert aux mises à jour et à la désinstallation).
AppId={{BCBBCE6C-61E3-41E0-831B-BBBAEDB21678}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
VersionInfoVersion={#AppVersion}
; Program Files (64 bits) ; « setup.exe /CURRENTUSER » permet une installation sans droits
; administrateur dans %LOCALAPPDATA%\Programs.
DefaultDirName={autopf}\{#AppName}
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=FileConverter-Setup-{#AppVersion}
SetupIconFile=..\file_converter\resources\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern dynamic
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Application PyInstaller (onedir), ffmpeg.exe et dossier licenses\ (ffmpeg, Qt/PySide6).
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
