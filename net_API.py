import requests
import urllib3
import time

# Disable SSL warnings for the local controller connection
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. CONFIGURATION ---
IMASTER_IP = "10.141.105.10"
USERNAME = "pythonalert"
PASSWORD = "Nesma10k@2025"

# Telegram Bot Details
TELE_TOKEN = "8679608431:AAGxbwri7v7UaP0J1-ooFQMPU_k0B5cUZyQ"
CHAT_ID = "5003052243"

# IDs identified from your F12 Inspect (image_7aff98.png)
# This parentId specifically points to your WAC/Building group
WAC_PARENT_ID = "87b9a793-9589-45da-912b-92eac5b4416e"

# --- 2. GLOBAL TRACKING ---
already_offline = set()

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("📲 Telegram alert sent successfully!")
        else:
            print(f"❌ Telegram Failed: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Telegram Connection Error: {e}")

def get_connection():
    # Login usually happens on 18002
    print(f"\n--- {time.strftime('%H:%M:%S')} | Attempting Login ---")
    url = f"https://{IMASTER_IP}:18002/controller/v2/tokens"
    credentials = {"userName": USERNAME, "password": PASSWORD}
    try:
        response = requests.post(url, json=credentials, verify=False, timeout=10)
        if response.status_code == 200:
            token = response.json().get("data", {}).get("token_id")
            print("✅ Login Successful!")
            return token
        else:
            print(f"❌ Login Failed! Code: {response.status_code}")
            return None
    except Exception as e:
        print(f"⚠️ Connection Error: {e}")
        return None

def monitor_nrc1_switches(token):
    global already_offline
    print(f"🔍 Scanning NRC1 Building (NR- Switches Only)...")
    
    # URL changed to Port 443 (removing :18002) as seen in your F12 capture
    url = f"https://{IMASTER_IP}/controller/campus/v2/devices/fitap/list"
    
    headers = {
        "X-ACCESS-TOKEN": token,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # JSON Payload matching the POST method required for /v2/ device lists
    payload = {
        "pageIndex": 1,
        "pageSize": 500,
        "parentId": WAC_PARENT_ID,
        "cascade": True
    }

    try:
        # Using POST as confirmed by your Headers screenshot
        response = requests.post(url, headers=headers, json=payload, verify=False, timeout=15)
        
        if response.status_code == 200:
            data = response.json().get("data", [])
            
            # --- THE PRECISION FILTER ---
            # 1. Name must start with 'NR-'
            # 2. Must NOT be an Access Point (AP)
            nrc1_switches = [
                d for d in data 
                if d.get("name", "").upper().startswith("NR-") 
                and "AP" not in d.get("model", "").upper()
            ]

            print(f"✅ Success! Port 443 Response Received.")
            print(f"📡 Monitoring {len(nrc1_switches)} NR-Switches.")

            current_offline_ips = set()
            for dev in nrc1_switches:
                status = dev.get("status")
                ip = dev.get("deviceIp")
                name = dev.get("name")

                # status 1 = Online. 0/2/4 = Offline/Alarm
                if status != 1:
                    current_offline_ips.add(ip)
                    if ip not in already_offline:
                        send_telegram_alert(f"🚨 <b>OFFLINE:</b> {name}\n📍 <b>IP:</b> {ip}")
                        print(f"🚨 ALERT: {name} ({ip}) is DOWN!")
                
                elif ip in already_offline:
                    send_telegram_alert(f"✅ <b>RECOVERED:</b> {name}\n📍 <b>IP:</b> {ip}")
                    print(f"✅ RECOVERY: {name} is back online!")

            # Update the tracking set for the next loop
            already_offline = current_offline_ips
            
        else:
            print(f"❌ API Error {response.status_code}: {response.text[:150]}")
            print("💡 If 404 persists, verify the 'tenant-id' in F12 Headers.")

    except Exception as e:
        print(f"⚠️ Monitor Loop Error: {e}")

# --- 3. EXECUTION LOOP ---
if __name__ == "__main__":
    print("🚀 NRC-1 10k Precision Switch Monitor Started...")
    while True:
        token = get_connection()
        if token:
            monitor_nrc1_switches(token)
            print("🕒 Waiting 60 seconds for next scan...")
            time.sleep(60)
        else:
            print("🔁 Retrying connection in 10s...")
            time.sleep(10)
