import os
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
data = requests.get(url).json()

print(data)