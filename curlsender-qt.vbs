Option Explicit

Const WINDOW_HIDDEN = 0
Const ICON_ERROR = 16

Dim shell, fso, scriptDir, pythonExe, targetScript
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
targetScript = scriptDir & "\curlsender_qt_boot.py"

If Not fso.FileExists(targetScript) Then
    MsgBox "Nao foi possivel localizar o bootstrap Qt V2 em:" & vbCrLf & vbCrLf & targetScript, ICON_ERROR, "cURLsender Qt V2"
    WScript.Quit 1
End If

pythonExe = ResolvePython(scriptDir)
If pythonExe = "" Then
    MsgBox "Python nao encontrado para iniciar a V2 em Qt." & vbCrLf & vbCrLf & _
        "Ordem tentada: .venv, venv, pyw, pythonw." & vbCrLf & _
        "Instale o Python para Windows ou crie uma virtualenv na pasta do projeto.", ICON_ERROR, "cURLsender Qt V2"
    WScript.Quit 1
End If

shell.Run BuildLaunchCommand(pythonExe, targetScript), WINDOW_HIDDEN, False

Function ResolvePython(baseDir)
    Dim candidates, i, candidate

    candidates = Array( _
        baseDir & "\.venv\Scripts\pythonw.exe", _
        baseDir & "\.venv\Scripts\python.exe", _
        baseDir & "\venv\Scripts\pythonw.exe", _
        baseDir & "\venv\Scripts\python.exe", _
        "pythonw.exe", _
        "python.exe", _
        "pyw.exe", _
        "py.exe" _
    )

    For i = 0 To UBound(candidates)
        candidate = candidates(i)
        If InStr(candidate, "\") > 0 Then
            If fso.FileExists(candidate) Then
                ResolvePython = candidate
                Exit Function
            End If
        Else
            ResolvePython = FindOnPath(candidate)
            If ResolvePython <> "" Then
                Exit Function
            End If
        End If
    Next

    ResolvePython = ""
End Function

Function FindOnPath(fileName)
    Dim pathValue, entries, i, entry, fullPath

    pathValue = shell.Environment("PROCESS")("PATH")
    entries = Split(pathValue, ";")

    For i = 0 To UBound(entries)
        entry = Trim(entries(i))
        If Len(entry) <> 0 Then
            If Left(entry, 1) = """" And Right(entry, 1) = """" Then
                entry = Mid(entry, 2, Len(entry) - 2)
            End If
            fullPath = entry
            If Right(fullPath, 1) <> "\" Then
                fullPath = fullPath & "\"
            End If
            fullPath = fullPath & fileName
            If fso.FileExists(fullPath) Then
                FindOnPath = fullPath
                Exit Function
            End If
        End If
    Next

    FindOnPath = ""
End Function

Function BuildLaunchCommand(pythonPath, scriptPath)
    Dim lowerName, command

    lowerName = LCase(fso.GetFileName(pythonPath))
    command = Quote(pythonPath)

    If lowerName = "pyw.exe" Or lowerName = "py.exe" Then
        command = command & " -3"
    End If

    BuildLaunchCommand = command & " " & Quote(scriptPath)
End Function

Function Quote(text)
    Quote = """" & text & """"
End Function
