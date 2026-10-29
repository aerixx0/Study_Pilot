# How to Open StudyPilot

**Current local platform: Windows only.** No macOS or Linux local package is available. The website remains available in a browser.

## Option 1: Open the website

**Website: [https://study-pilot-olive.vercel.app/](https://study-pilot-olive.vercel.app/)**

No download or Python installation is required. Open the link in your browser and register an account. Choose English or Simplified Chinese using the language selector.

## Option 2: Download and run on Windows

**[Download StudyPilot for Windows (.zip)](https://github.com/aerixx0/Study_Pilot/releases/download/v0.6.0-preview.2/StudyPilot-Windows-v0.6.0-preview.2.zip)**

### One-command PowerShell download

Copy this command into Windows PowerShell. It downloads the ZIP to your Desktop:

```powershell
$studyPilotZip = Join-Path ([Environment]::GetFolderPath('Desktop')) 'StudyPilot-Windows-v0.6.0-preview.2.zip'; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/aerixx0/Study_Pilot/releases/download/v0.6.0-preview.2/StudyPilot-Windows-v0.6.0-preview.2.zip' -OutFile $studyPilotZip
```

This ZIP contains the application source and a startup script. It is not a standalone `.exe` installer. The local Streamlit interface is currently Chinese; use the website for English.

### 1. Install Python

Install **Python 3.12 or later** from [the official Windows downloads page](https://www.python.org/downloads/windows/). With the classic installer, select **Add python.exe to PATH**. If Python 3.12 or later is already installed and available through `py` or `python`, skip this step.

### 2. Download and extract

Download the ZIP using the link above. Right-click the downloaded file and choose **Extract All**. Open the extracted **`StudyPilot-Windows`** folder. Do not run the launcher from inside the ZIP preview.

### 3. Start the application

Double-click **`Start-StudyPilot.cmd`** in that folder.

On the first launch, the script creates a Python virtual environment and downloads dependencies. An internet connection is required for this setup. Keep the startup window open and wait for it to finish. The browser opens automatically when the app is ready.

**Local address: [http://127.0.0.1:8501/](http://127.0.0.1:8501/)**

If the browser does not open automatically, open this local address yourself after startup completes. The address works only while the local service is running on your computer.

### 4. Stop or reopen

Press **Ctrl+C** in the startup window to stop the service. To use it again, double-click **`Start-StudyPilot.cmd`**. Keep the entire extracted folder together.

## If startup fails

- **Python cannot be found:** Install Python 3.12 or later, enable its PATH option if offered, then reopen the launcher.
- **Dependency installation fails:** Check your internet connection and the error shown in the startup window, then retry.
- **The browser cannot open the local address:** Wait for installation and startup to finish. Keep the startup window open and check it for errors.
- **Port 8501 is already in use:** Close an earlier StudyPilot startup window and retry. Do not stop unrelated applications.

The automatically generated **Source code (zip)** and **Source code (tar.gz)** links on GitHub are general repository archives. For the Windows steps above, use the named **`StudyPilot-Windows-v0.6.0-preview.2.zip`** download.

## Your data

The website and local application have separate accounts and study records, with no automatic synchronization. Register separately for each installation you use.

Local accounts and study records are stored under `python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/data`. Include that folder in backups. Do not replace it when updating application files. If you move the application folder, recreate its `.venv` virtual environment in the new location.

Core goals, tasks, planning, and records work without AI. Model requests require server-side `ZHIPU_API_KEY` and/or `SILICONFLOW_API_KEY` environment variables. See the [AI configuration guide](README.md#ai-configuration-and-confirmation). Keep API keys, recovery codes, database connection strings, and local data private.
