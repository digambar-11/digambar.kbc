import subprocess
import platform
import time
import requests

# --- CONFIGURATION ---
# Add all 55+ switches here. Format: "IP": "Name"
SWITCHES = {
    "172.25.0.60": "Access-SW-01",
    # "172.25.0.61": "Access-SW-02",
    # "IP": "Name",
}

TELE_TOKEN = "8679608431:AAGxbwri7v7UaP0J1-ooFQMPU_k0B5cUZyQ"
CHAT_ID = "5003052243"

# This dictionary tracks the last known state of every switch
# It starts as 'True' (Online) so you don't get alerts when the script starts
last_state = {ip: True for ip in SWITCHES}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def is_online(ip):
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    # -w 1000 ensures we don't wait more than 1 second per switch
    command = ['ping', param, '1', '-w', '1000', ip]
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        return result.returncode == 0
    except:
        return False

if __name__ == "__main__":
    print(f"🚀 Background Monitor Active. Checking {len(SWITCHES)} devices every 60s...")
    # No send_telegram() here, so it starts silently.

    while True:
        for ip, name in SWITCHES.items():
            current_status = is_online(ip)
            
            # If it was ONLINE but now it is OFFLINE
            if last_state[ip] and not current_status:
                msg = f"🚨 <b>OFFLINE:</b> {name}\n📍 IP: {ip}\n⏰ Time: {time.strftime('%H:%M:%S')}"
                print(f"ALERT: {name} is DOWN")
                send_telegram(msg)
                last_state[ip] = False # Update state to prevent double messages
            
            # If it was OFFLINE but now it is back ONLINE
            elif not last_state[ip] and current_status:
                msg = f"✅ <b>RECOVERED:</b> {name}\n📍 IP: {ip}"
                print(f"INFO: {name} is back UP")
                send_telegram(msg)
                last_state[ip] = True # Update state
        
        # Check the console to see the script is still alive
        print(f"Check completed at {time.strftime('%H:%M:%S')}. Waiting 60s...")
        time.sleep(60)
