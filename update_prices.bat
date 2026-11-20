@echo off
REM Nama-Mandi daily price update: fetch prices, save, push to GitHub.
REM API key is read from key.txt (never uploaded).
cd /d "%~dp0"

if not exist key.txt (
  echo key.txt not found. Put your data.gov.in API key in key.txt
  pause
  exit /b 1
)
set /p DATA_GOV_API_KEY=<key.txt

echo ===== %date% %time% ===== >> update_log.txt
git pull --rebase --autostash >> update_log.txt 2>&1
python scripts\update_prices.py >> update_log.txt 2>&1

git add data state
git diff --cached --quiet && (
  echo No new prices today. >> update_log.txt
) || (
  git commit -m "Prices updated %date%" >> update_log.txt 2>&1
  git push >> update_log.txt 2>&1
)
echo Done. >> update_log.txt