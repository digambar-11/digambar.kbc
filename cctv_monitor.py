import subprocess
import platform
import time
import requests
import ast
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor

# --- 1. CONFIGURATION ---
TELE_TOKEN = "8679608431:AAGxbwri7v7UaP0J1-ooFQMPU_k0B5cUZyQ"
CHAT_ID_CCTV = "5003052243"

# Gmail SMTP Config
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_SENDER = "digambarkokitkar11@gmail.com"
EMAIL_PASSWORD = "tdmm fyde nxkt dcia" 

# Recipients
TO_EMAILS = ["digambarkokitkar11@gmail.com"]
CC_EMAILS = ["kokitkardigamber11@gmail.com"]

CONFIG_FILE = "cctvdevices.txt"
OFFLINE_THRESHOLD = 1200   # Set to 1200 for 20 mins in production
RECOVERY_STABILITY = 1200 # 20 minutes stability check

# Tracking dictionaries
last_state = {}       
pending_offline = {}  
pending_recovery = {} # New: Tracks uptime for stability check

# --- 2. CORE FUNCTIONS ---

def load_device_dict():
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: {CONFIG_FILE} not found!")
        return {}
    with open(CONFIG_FILE, 'r') as f:
        return ast.literal_eval(f.read().strip())

def is_online(ip):
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    try:
        result = subprocess.run(['ping', param, '1', '-w', '1000', ip], 
                                capture_output=True, text=True, timeout=3, creationflags=0x08000000)
        return "TTL=" in result.stdout
    except:
        return False

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID_CCTV, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def get_telegram_reply(cam_name, prompt_type="Work Order"):
    """Generic listener for WO or Recovery Reason"""
    print(f"📥 Waiting for Telegram {prompt_type} input for {cam_name}...")
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates"
    
    last_id = 0
    try:
        resp = requests.get(url).json()
        if resp["result"]:
            last_id = resp["result"][-1]["update_id"]
    except: pass

    while True:
        try:
            resp = requests.get(url, params={"offset": last_id + 1}, timeout=10).json()
            for update in resp.get("result", []):
                msg_text = update.get("message", {}).get("text")
                if msg_text:
                    print(f"✅ {prompt_type} Received: {msg_text}")
                    return msg_text
        except: pass
        time.sleep(3)

def send_dashboard_email(cam, status, detail_label, detail_value):
    """Universal Email Function for Alerts and Recoveries"""
    devices = load_device_dict()
    total = len(devices)
    color = "#dc3545" if status == "OFFLINE" else "#28a745"
    subject = f"{'🚨' if status == 'OFFLINE' else '✅'} MONITORING: {cam['name']} is {status}"

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <div style="max-width: 600px; margin: auto; border: 1px solid #eee; padding: 20px; border-radius: 10px;">
            <h2 style="color: #2c3e50;">NRC-1 CCTV Status Dashboard</h2>
            <p>Reported at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <table width="100%" border="1" cellpadding="10" style="border-collapse: collapse; font-size: 13px;">
                <tr style="background-color: {color}; color: white;">
                    <th>Location</th><th>Asset #</th><th>Status</th><th>{detail_label}</th>
                </tr>
                <tr>
                    <td>{cam['location']}</td><td>{cam['name']}</td><td><b>{status}</b></td><td>{detail_value}</td>
                </tr>
            </table>
            <p style="font-size: 12px; color: #95a5a6; margin-top: 20px;">NRC-1 Automation Bot | Ras Alsheikh Hamid</p>
        </div>
    </body>
    </html>
    """
    try:
        msg = MIMEMultipart(); msg['From'] = EMAIL_SENDER; msg['To'] = ", ".join(TO_EMAILS)
        msg['Cc'] = ", ".join(CC_EMAILS); msg['Subject'] = subject
        msg.attach(MIMEText(html, 'html'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT); server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, TO_EMAILS + CC_EMAILS, msg.as_string())
        server.quit()
        print(f"📧 Email Sent for {cam['name']}")
    except Exception as e:
        print(f"❌ Mail Error: {e}")

# --- 3. MONITORING LOOP ---

def run_monitor():
    global last_state, pending_offline, pending_recovery
    devices = load_device_dict()
    ips = list(devices.keys())
    now_ts = time.time()
    
    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(is_online, ips))

    for i, ip in enumerate(ips):
        online = results[i]
        cam = devices[ip]
        if ip not in last_state: last_state[ip] = True

        # --- CASE: DEVICE IS DOWN ---
        if not online:
            # Clear recovery timer if it drops again during stability check
            if ip in pending_recovery:
                del pending_recovery[ip]
                print(f"⚠️ {cam['name']} dropped during stability check. Resetting.")

            if last_state[ip]: 
                if ip not in pending_offline:
                    pending_offline[ip] = now_ts
                elif (now_ts - pending_offline[ip]) >= OFFLINE_THRESHOLD:
                    last_state[ip] = False
                    del pending_offline[ip]
                    send_telegram(f"🚨 <b>{cam['name']} OFFLINE</b>\n👉 Type <b>Work Order</b> number:")
                    user_wo = get_telegram_reply(cam['name'], "Work Order")
                    send_dashboard_email(cam, "OFFLINE", "Work Order / DLP", user_wo)
                    send_telegram(f"✅ Alert Sent with WO: {user_wo}")

        # --- CASE: DEVICE IS UP ---
        else:
            # If it was previously offline, start 20-min recovery stability check
            if not last_state[ip]:
                if ip not in pending_recovery:
                    pending_recovery[ip] = now_ts
                    print(f"⏳ Stability check started for {cam['name']} (20 mins)")
                
                elif (now_ts - pending_recovery[ip]) >= RECOVERY_STABILITY:
                    # Successfully stable for 20 mins
                    last_state[ip] = True
                    del pending_recovery[ip]
                    send_telegram(f"✅ <b>{cam['name']} STABLE (20m)</b>\n👉 Please type the <b>REASON</b> for the outage:")
                    reason = get_telegram_reply(cam['name'], "Recovery Reason")
                    send_dashboard_email(cam, "ONLINE", "Root Cause / Reason", reason)
                    send_telegram(f"📧 Recovery Report Sent: {reason}")
            
            # Clean up offline timer if it was just a blip
            if ip in pending_offline:
                del pending_offline[ip]

if __name__ == "__main__":
    print("\n🚀 NRC-1 DASHBOARD AUTOMATION ONLINE")
    send_telegram(f"🚀 <b>NRC-1 MONITORING ONLINE</b>\n📡 Scanning {len(load_device_dict())} cameras.")

    while True:
        run_monitor()
        time.sleep(20)
