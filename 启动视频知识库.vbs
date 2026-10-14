' Launch VideoKnowledgeBase with no console window at all.
'
' Why this file exists: the .bat runs cmd.exe, so double-clicking it ALWAYS
' opens a black console window -- that is not the Python subprocess flash,
' it is the batch script's own window. This wrapper starts pythonw.exe
' (GUI subsystem) with window style 0 (hidden), so nothing appears.
'
' Keep this file PURE ASCII. wscript reads .vbs using the system ANSI code
' page; non-ASCII comments or strings would be mangled or break parsing.
' (Only the file NAME has Chinese characters, which is fine on NTFS.)

Option Explicit

Dim fso, sh, base, pyw, app, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = base & "\venv\Scripts\pythonw.exe"
app = base & "\src\app_web.py"

If Not fso.FileExists(pyw) Then
  MsgBox "pythonw.exe not found:" & vbCrLf & pyw, 16, "VideoKnowledgeBase"
  WScript.Quit 1
End If
If Not fso.FileExists(app) Then
  MsgBox "app_web.py not found:" & vbCrLf & app, 16, "VideoKnowledgeBase"
  WScript.Quit 1
End If

sh.CurrentDirectory = base
cmd = """" & pyw & """ """ & app & """"
' 0 = hidden window, False = do not wait for it to finish
sh.Run cmd, 0, False
