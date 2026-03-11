import subprocess
import platform
import time
import requests
import csv
import os
from datetime import datetime, timedelta

# --- 1. CONFIGURATION ---
# Telegram Details
TELE_TOKEN = "8679608431:AAGxbwri7v7UaP0J1-ooFQMPU_k0B5cUZyQ"
CHAT_ID = "5003052243"

# File & Retention
LOG_FILE = "downtime_log.csv"
RETENTION_DAYS = 90

# Monitoring List (Add all your NRC-1 switches here)
SWITCHES = {
    "172.25.0.60": "Access-SW-01",
    # "172.25.0.61": "Access-SW-02",
}

# State Trackers
last_state = {ip: True for ip in SWITCHES}
down_time_start = {ip: 0 for ip in SWITCHES}

# --- 2. CORE FUNCTIONS ---

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def log_event(name, ip, event_type, duration="N/A"):
    """Saves logs to CSV with DD-MM-YYYY formatting"""
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

def clean_old_logs():
    """Maintains a rolling 90-day history"""
    if not os.path.exists(LOG_FILE): return
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    rows_to_keep = []
    try:
        with open(LOG_FILE, mode='r') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            for row in reader:
                if datetime.strptime(row['Date'], '%d-%m-%Y') > cutoff:
                    rows_to_keep.append(row)
        with open(LOG_FILE, mode='w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows_to_keep)
        print(f"🧹 Cleanup: Keeping last {RETENTION_DAYS} days of logs.")
    except Exception as e:
        print(f"⚠️ Cleanup error: {e}")

def send_daily_summary():
    """Generates the 8:00 AM Daily Morning Report from the CSV"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%d-%m-%Y')
    incidents = 0
    downtime = 0.0
    affected = set()

    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, mode='r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['Date'] == yesterday and row['Event'] == 'RECOVERED':
                    incidents += 1
                    downtime += float(row['Duration (Mins)'])
                    affected.add(row['Device Name'])

    if incidents == 0:
        msg = f"☀️ <b>DAILY REPORT: {yesterday}</b>\n🟢 Perfect Uptime! All switches were stable."
    else:
        msg = f"☀️ <b>DAILY REPORT: {yesterday}</b>\n⚠️ Incidents: {incidents}\n⏳ Total Down: {round(downtime, 2)}m\n🏢 Affected: {', '.join(affected)}"
    send_telegram(msg)

def is_last_day_of_month():
    today = datetime.now()
    return (today + timedelta(days=1)).month != today.month

def is_online(ip):
    """Checks device status via ICMP Ping"""
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    # Wait time set to 1 second
    command = ['ping', param, '1', '-w', '1000', ip]
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        return result.returncode == 0
    except: return False

# --- 3. MAIN MONITORING LOOP ---

if __name__ == "__main__":
    print(f"🚀 Python Alert System Active. Monitoring {len(SWITCHES)} devices.")
    clean_old_logs() # Run cleanup on start
    
    daily_sent = False
    monthly_sent = False

    while True:
        now = datetime.now()

        # Morning Report at 08:00
        if now.hour == 8 and now.minute == 0 and not daily_sent:
            send_daily_summary()
            daily_sent = True
        
        # Monthly Summary Alert on Last Day at 23:00
        if is_last_day_of_month() and now.hour == 23 and not monthly_sent:
            send_telegram(f"📊 <b>MONTHLY NOTICE:</b> Your 90-day downtime log is ready for review.")
            monthly_sent = True

        # Reset flags and run cleanup at midnight
        if now.hour == 0 and now.minute == 0:
            daily_sent = False
            monthly_sent = False
            clean_old_logs()

        # Scan each switch in the list
        for ip, name in SWITCHES.items():
            current_status = is_online(ip)
            
            # Change from ONLINE to OFFLINE
            if last_state[ip] and not current_status:
                down_time_start[ip] = time.time()
                send_telegram(f"🚨 <b>OFFLINE:</b> {name}\n📍 IP: {ip}\n⏰ {now.strftime('%H:%M:%S')}")
                log_event(name, ip, "OFFLINE")
                last_state[ip] = False
            
            # Change from OFFLINE to ONLINE
            elif not last_state[ip] and current_status:
                mins = round((time.time() - down_time_start[ip]) / 60, 2)
                send_telegram(f"✅ <b>RECOVERED:</b> {name}\n⏳ IP: {ip}\n⏰ Down for: {mins}\n⏰ {now.strftime('%H:%M:%S')}")
                log_event(name, ip, "RECOVERED", mins)
                last_state[ip] = True
        
        print(f"✅ Check finished at {now.strftime('%H:%M:%S')}. Waiting 30s...")
        time.sleep(30)
