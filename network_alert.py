import subprocess
import platform
import time
import requests
import ast
import csv
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURATION ---
TELE_TOKEN = "8679608431:AAGxbwri7v7UaP0J1-ooFQMPU_k0B5cUZyQ"
CHAT_ID = "5003052243"
LOG_FILE = "downtime_log.csv"
CONFIG_FILE = "devices.txt" 

# Memory is empty every time the script starts (Requirement #3)
last_state = {}
down_time_start = {}

def load_device_dict():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, 'r') as f:
        return ast.literal_eval(f.read().strip())

def is_online(ip):
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    # Requirement #1: creationflags=0x08000000 prevents CMD windows from popping up
    command = ['ping', param, '1', '-w', '1000', ip]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, creationflags=0x08000000)
        return "TTL=" in result.stdout
    except:
        return False

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except: pass

def log_event(name, ip, event_type, duration="N/A"):
    # Requirement #2: Appends to the same file every time (Single Storage)
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['Date', 'Time', 'Device Name', 'IP Address', 'Event', 'Duration (Mins)'])
        writer.writerow([datetime.now().strftime('%d-%m-%Y'), datetime.now().strftime('%H:%M:%S'), name, ip, event_type, duration])

def run_monitor_once():
    global last_state, down_time_start
    SWITCHES = load_device_dict()
    if not SWITCHES: return

    ips = list(SWITCHES.keys())
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(is_online, ips))

    for i, ip in enumerate(ips):
        current_status = results[i]
        name = SWITCHES.get(ip, "Unknown")
        
        # Fresh Memory Logic: If not in memory, force 'True' to trigger alert if it's actually 'False'
        if ip not in last_state:
            last_state[ip] = True 
            down_time_start[ip] = time.time() if not current_status else 0
        
        if last_state[ip] and not current_status: 
            down_time_start[ip] = time.time()
            send_telegram(f"🚨 <b>OFFLINE:</b> {name}\n📍 IP: {ip}")
            log_event(name, ip, "OFFLINE")
            last_state[ip] = False
            
        elif not last_state[ip] and current_status: 
            mins = round((time.time() - down_time_start.get(ip, time.time())) / 60, 2)
            send_telegram(f"✅ <b>RECOVERED:</b> {name}\n📍 IP: {ip}\n⏳ Down for: {mins} mins")
            log_event(name, ip, "RECOVERED", mins)
            last_state[ip] = True

if __name__ == "__main__":
    # Delay for stability
    time.sleep(60) 
    send_telegram("🖥️ <b>System Start:</b> Monitoring refreshed and active.")

    while True:
        try:
            run_monitor_once()
            # Daily Heartbeat at 8 AM
            now = datetime.now()
            if now.hour == 8 and now.minute == 0 and now.second < 45:
                send_telegram("☀️ <b>Daily Report:</b> Monitoring is active.")
                time.sleep(45)
            time.sleep(30)
        except:
            time.sleep(60)
