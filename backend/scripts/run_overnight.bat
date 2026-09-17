@echo off
REM One-click overnight extraction. Double-click this before going to bed.
REM
REM It walks the queue sheet subject by subject, two chapters at a time, and
REM keeps going until the sheet is empty or the stop time arrives. Everything
REM it finishes is in the database; everything it does not is still pending in
REM the sheet, so running it again the next night simply continues.

setlocal
cd /d "%~dp0\.."

if not exist "venv\Scripts\python.exe" (
    echo Could not find venv\Scripts\python.exe in %CD%
    echo Create the environment first, then run this again.
    pause
    exit /b 1
)

echo ======================================================================
echo  Overnight chapter extraction
echo  Started: %DATE% %TIME%
echo ======================================================================
echo.
echo  Close Excel if the queue sheet is open, or progress can only be
echo  written to the ledger. The run itself is unaffected either way.
echo.

REM No stop time on purpose. It runs until the queue is empty, however long
REM that takes, and you stop it yourself in the morning -- from the Overnight
REM page in the web app, or by closing this window. Either way the chapter in
REM progress is finished and saved first.
venv\Scripts\python.exe -m scripts.run_extraction_queue %*

set CODE=%ERRORLEVEL%
echo.
echo ======================================================================
echo  Finished: %DATE% %TIME%   (exit code %CODE%)
echo  Logs: backend\logs\  --  Sheet: backend\queue\extraction_queue.xlsx
echo ======================================================================
pause
exit /b %CODE%
