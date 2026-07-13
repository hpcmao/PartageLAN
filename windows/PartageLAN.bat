@echo off
rem Lance PartageLAN en arriere-plan (icone dans la zone de notification), sans console.
rem Double-clic pour demarrer. Si l'app tourne deja, ce lanceur ne fait rien (anti-doublon).
start "" "C:\Users\winjeux\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\pythonw.exe" "%~dp0partagelan_tray.py"
