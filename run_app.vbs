Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

currentFolder = fso.GetParentFolderName(WScript.ScriptFullName)

exePath = currentFolder & "\USBSave.exe"

WshShell.Run """" & exePath & """ --cli --no-notify", 0, False

Set WshShell = Nothing
Set fso = Nothing
