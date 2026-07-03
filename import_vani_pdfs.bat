@echo off
cd /d "%~dp0"

echo Importing PDFs from C:\nidhivan\Vani PDF
echo Existing books and empty PDF files will be skipped.
echo.

.\.venv\Scripts\python.exe manage.py import_pdf_folder "C:\nidhivan\Vani PDF" --category Vani

echo.
echo Done. Press any key to close.
pause > nul
