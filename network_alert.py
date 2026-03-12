import subprocess
import platform
import time
import requests
import ast
import csv
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- 1. CONFIGURATION ---
TELE_TOKEN = "8679608431:AAGxbwri7v7UaP0J1-ooFQMPU_k0B5cUZyQ"
CHAT_ID = "5003052243"
LOG_FILE = "downtime_log.csv"
CONFIG_FILE = "devices.txt" 
RETENTION_DAYS = 90

last_state = {}
down_time_start = {}

# --- 2. CORE FUNCTIONS ---

def load_device_dict():
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Configuration file {CONFIG_FILE} is missing!")
    with open(CONFIG_FILE, 'r') as f:
        data = f.read().strip()
        return ast.literal_eval(data)

def is_online(ip):
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    command = ['ping', param, '1', '-w', '1000', ip]
    result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    return "TTL=" in result.stdout

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try: 
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"📡 Telegram Send Failed: {e}")

def log_event(name, ip, event_type, duration="N/A"):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['Date', 'Time', 'Device Name', 'IP Address', 'Event', 'Duration (Mins)'])
        writer.writerow([
            datetime.now().strftime('%d-%m-%Y'),
            datetime.now().strftime('%H:%M:%S'),
            name, ip, event_type, duration
        ])

# --- 3. THE MONITOR ENGINE ---

def run_monitor_once():
    global last_state, down_time_start
    
    SWITCHES = load_device_dict()
    ips = list(SWITCHES.keys())
    
    for ip in ips:
        if ip not in last_state:
            last_state[ip] = True
            down_time_start[ip] = 0

    now = datetime.now()
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(is_online, ips))

    for i, ip in enumerate(ips):
        current_status = results[i]
        name = SWITCHES[ip]
        
        if last_state[ip] and not current_status: # Switch went Offline
            down_time_start[ip] = time.time()
            send_telegram(f"🚨 <b>OFFLINE:</b> {name}\n📍 IP: {ip}\n⏰ {now.strftime('%H:%M:%S')}")
            log_event(name, ip, "OFFLINE")
            last_state[ip] = False
            
        elif not last_state[ip] and current_status: # Switch Recovered
            mins = round((time.time() - down_time_start[ip]) / 60, 2)
            send_telegram(f"✅ <b>RECOVERED:</b> {name}\n📍 IP: {ip}\n⏳ Down for: {mins} mins")
            log_event(name, ip, "RECOVERED", mins)
            last_state[ip] = True
    
    print(f"✅ Check finished at {now.strftime('%H:%M:%S')}. Waiting 30s...")

# --- 4. THE UNIVERSAL WATCHDOG ---

if __name__ == "__main__":
    send_telegram("🖥️ <b>System Start:</b> Monitoring active at NRC-1.")
    print("🖥️  Monitoring active. Initializing state...")
    
    try:
        SWITCHES = load_device_dict()
        ips = list(SWITCHES.keys())
        
        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(is_online, ips))
        
        for i, ip in enumerate(ips):
            status = results[i]
            if status:
                # Device is ONLINE: Set it to True so it stays silent
                last_state[ip] = True
                down_time_start[ip] = 0
            else:
                # Device is OFFLINE: Set it to True (FOOL the script)
                # This makes the script think it was Online, so when the 
                # first loop runs, it detects a "Change" to Offline and alerts you!
                last_state[ip] = True 
                down_time_start[ip] = time.time()
                
        print(f"✅ State initialized. Offline devices will alert in 30 seconds.")
    except Exception as init_err:
        print(f"⚠️ Initial scan error: {init_err}")

    error_active = False 
    # ... rest of your code

    while True:
        try:
            if error_active:
                send_telegram("✅ <b>RECOVERY:</b> Error resolved. Monitoring resumed.")
                log_event("SYSTEM", "N/A", "SCRIPT_RECOVERED")
                error_active = False 

            # Run the scan (Now it will only alert if a status CHANGES)
            run_monitor_once()

            # --- HEARTBEAT CHECK ---
            now = datetime.now()
            if now.hour == 8 and now.minute == 0 and now.second < 40:
                send_telegram("☀️ <b>Daily Report:</b> NRC-1 Monitoring is active. All systems are being tracked.")
                time.sleep(40) 

            time.sleep(30)
            
        except KeyboardInterrupt:
            print("\n🛑 Stopped manually. Exiting...")
            break

        except Exception as e:
            error_str = str(e)[:150]
            if not error_active:
                timestamp = datetime.now().strftime('%H:%M:%S')
                error_alert = (
                    f"⚠️ <b>SCRIPT ERROR / CRASH</b>\n"
                    f"⏰ Time: {timestamp}\n"
                    f"❌ Error: {error_str}\n"
                    f"🔄 <i>Status: Retrying in 60s...</i>"
                )
                send_telegram(error_alert)
                log_event("SYSTEM", "N/A", f"SCRIPT_CRASH: {error_str}")
                error_active = True
            
            print(f"⏳ Error persists: {error_str}. Retrying...")
            time.sleep(60)
