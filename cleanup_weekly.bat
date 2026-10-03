@echo off
REM Weekly retention cleanup for List_agg / List_agg_NASDAQ.
REM Triggered by Windows Task Scheduler -- see README.md "Weekly cleanup" section.
REM Runs even if no Claude Code / chat session is open.

cd /d "C:\Users\abrah\OneDrive\Documents\Trading\Qtrade"
echo ---- %date% %time% ---- >> cleanup_log.txt
"C:\Users\abrah\OneDrive\Documents\Trading\Qtrade\.venv\Scripts\python.exe" cleanup_list_agg.py >> cleanup_log.txt 2>&1
