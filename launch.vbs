Dim scriptDir
scriptDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))

Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "python """ & scriptDir & "app.py""", 0, False

WScript.Sleep 1500
WshShell.Run "cmd /c start """" ""http://localhost:5000""", 0, False
