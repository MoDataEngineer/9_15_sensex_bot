import os
import requests
from dotenv import load_dotenv

load_dotenv()

client_id = os.getenv("DHAN_CLIENT_ID")
access_token = os.getenv("DHAN_ACCESS_TOKEN")

if not client_id or not access_token:
    raise RuntimeError("Dhan credentials are missing from .env")

url = "https://api.dhan.co/v2/profile"

headers = {
    "access-token": access_token,
    "client-id": client_id,
}

response = requests.get(url, headers=headers, timeout=10)

print("HTTP Status:", response.status_code)
print("Response:")
print(response.text)