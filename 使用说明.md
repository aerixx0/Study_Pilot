# Running StudyPilot Locally

Double-click `Start-StudyPilot.cmd` in this folder to start the application, then open [StudyPilot](http://127.0.0.1:8501/) in your browser. Closing the startup window stops the service. Double-click the script again to restart it.

The application source code and local data are located in `python-ai-agent-ai-agent-studypilot/outputs/StudyPilot`. Its `data` folder stores existing accounts and study records. Keep the entire application folder, and include `data` in your backups.

On this computer, the Python runtime (`.runtime/python`) and the application's virtual environment (`.venv`) are already set up on drive D. Starting the local application does not depend on the original project folder on drive C. The Git repository is also retained for further development. Do not move `.venv` on its own; recreate the virtual environment if you move the project root folder.

Hosted website: [StudyPilot](https://study-pilot-olive.vercel.app/)

The local application uses SQLite, while the hosted application uses Neon PostgreSQL. Their accounts and study records are separate. Existing local accounts can still sign in locally; you must register separately on the hosted website. The cloud database does not overwrite local records.

The AI assistant requires API keys for the configured free models: `ZHIPU_API_KEY` for the primary provider and `SILICONFLOW_API_KEY` for the fallback provider. Model requests are unavailable if neither key is configured. Do not commit API keys, database connection strings, the `data` folder, or runtime files to Git.
