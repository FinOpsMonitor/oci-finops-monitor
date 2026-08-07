@echo off
REM Launches the OCI FinOps Monitor dashboard.
REM Double-click this file, or schedule it with Windows Task Scheduler.

cd /d "%~dp0"

IF NOT EXIST venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing/updating dependencies...
pip install -q -r requirements.txt

echo Starting dashboard at http://localhost:8501 ...
streamlit run app.py

pause
