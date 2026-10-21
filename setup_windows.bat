@echo off
REM One-click setup + run on Windows (run from the project folder)
py -3 -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :err
python -m pytest -q || goto :err
python run_pipeline.py || goto :err
echo.
echo Done. Start the dashboard with:  .venv\Scripts\activate  then  streamlit run app\streamlit_app.py
goto :eof
:err
echo Setup failed - see messages above.
exit /b 1
