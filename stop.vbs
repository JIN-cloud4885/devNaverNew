Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -aon ^| findstr :5000') do taskkill /F /PID %a", 0, True
MsgBox "네이버 기사 검색기가 종료되었습니다.", 64, "종료"
