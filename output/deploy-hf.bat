@echo off
REM ==========================================
REM OpenCrew — Deploy to Hugging Face Spaces
REM ==========================================

echo.
echo ========================================
echo   OpenCrew — Hugging Face Spaces Deploy
echo ========================================
echo.

REM Check if HF CLI is installed
where huggingface-cli >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Hugging Face CLI not found!
    echo Install it with: pip install huggingface_hub
    echo.
    pause
    exit /b 1
)

REM Check if logged in
echo [1/5] Checking HF login...
huggingface-cli whoami
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Not logged in. Run: huggingface-cli login
    pause
    exit /b 1
)

echo.
echo [2/5] Preparing files...

REM Create temp directory for HF Space
if exist "%TEMP%\opencrew-hf" rmdir /s /q "%TEMP%\opencrew-hf"
mkdir "%TEMP%\opencrew-hf"

REM Copy necessary files
copy Dockerfile.hf "%TEMP%\opencrew-hf\Dockerfile"
copy supervisord.conf "%TEMP%\opencrew-hf\"
copy start.sh "%TEMP%\opencrew-hf\"
copy README_hf.md "%TEMP%\opencrew-hf\README.md"
copy .gitignore "%TEMP%\opencrew-hf\"

REM Copy directories
xcopy /E /I shared "%TEMP%\opencrew-hf\shared"
xcopy /E /I agents "%TEMP%\opencrew-hf\agents"
xcopy /E /I web "%TEMP%\opencrew-hf\web"

echo.
echo [3/5] Files prepared in: %TEMP%\opencrew-hf
echo.

REM Ask for Space name
set /p SPACE_NAME="Enter your HF Space name (e.g., Binh151412/opencrew): "

echo.
echo [4/5] Uploading to HF Space: %SPACE_NAME%
echo.

REM Upload files using huggingface-cli
cd /d "%TEMP%\opencrew-hf"

REM Initialize git repo
git init
git add .
git commit -m "Initial OpenCrew deployment"

REM Add HF remote
git remote add origin https://huggingface.co/spaces/%SPACE_NAME%

REM Push to HF
echo Pushing to Hugging Face...
git push --force origin main

echo.
echo [5/5] Deploy complete!
echo.
echo ========================================
echo   Your Space: https://huggingface.co/spaces/%SPACE_NAME%
echo   Direct URL: https://%SPACE_NAME:~0,-1%-%SPACE_NAME:~-1%.hf.space
echo ========================================
echo.
echo IMPORTANT: Set these environment variables in Space Settings:
echo   - MIMO_API_KEY (required)
echo   - MIMO_BASE_URL (optional)
echo   - GITHUB_TOKEN (optional)
echo.

pause
