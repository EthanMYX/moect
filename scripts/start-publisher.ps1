param([string]$PythonPath = "$env:LOCALAPPDATA\Programs\WeChatMsg\.venv311\Scripts\pythonw.exe")
$publisherSource = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Python environment not found; provide -PythonPath.' }
Start-Process -FilePath $PythonPath -ArgumentList @('publisher_app.py') -WorkingDirectory $publisherSource -WindowStyle Hidden
