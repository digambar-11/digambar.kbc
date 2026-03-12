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

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_SENDER = "digambarkokitkar11@gmail.com"
EMAIL_PASSWORD = "tdmm fyde nxkt dcia" 

TO_EMAILS = ["digambarkokitkar11@gmail.com"]
CC_EMAILS = ["kokitkardigamber11@gmail.com"]

CONFIG_FILE = "devices - Copy.txt"
INCIDENT_FILE = "active_incidents.txt" 

OFFLINE_THRESHOLD = 1200   # 20 mins
RECOVERY_STABILITY = 1200  # 20 mins

# Tracking dictionaries
last_state = {}       
pending_offline = {}  
pending_recovery = {} 

# --- 2. CORE FUNCTIONS ---

def load_device_dict():
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: {CONFIG_FILE} not found!")
        return {}
    with open(CONFIG_FILE, 'r') as f:
        return ast.literal_eval(f.read().strip())

def save_active_incidents(incidents_dict):
    """Saves a dictionary of {cam_name: work_order}"""
    with open(INCIDENT_FILE, 'w') as f:
        f.write(str(incidents_dict))

def load_active_incidents():
    """Loads the dictionary of active incidents"""
    if not os.path.exists(INCIDENT_FILE): return {}
    try:
        with open(INCIDENT_FILE, 'r') as f:
            return ast.literal_eval(f.read().strip())
    except: return {}

def is_online(ip):
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    try:
        result = subprocess.run(['ping', param, '1', '-w', '1000', ip], 
                                capture_output=True, text=True, timeout=3, creationflags=0x08000000)
        return "TTL=" in result.stdout
    except: return False

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID_CCTV, "text": message, "parse_mode": "HTML"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def get_telegram_reply(cam_name, prompt_type="Work Order"):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates"
    last_id = 0
    try:
        resp = requests.get(url).json()
        if resp["result"]: last_id = resp["result"][-1]["update_id"]
    except: pass

    while True:
        try:
            resp = requests.get(url, params={"offset": last_id + 1}, timeout=10).json()
            for update in resp.get("result", []):
                msg_text = update.get("message", {}).get("text")
                if msg_text: return msg_text
        except: pass
        time.sleep(3)

def send_batch_dashboard_email(cam_list, status="OFFLINE"):
    devices = load_device_dict()
    total_count = len(devices)
    
    current_active_incidents = load_active_incidents()
    offline_count = len(current_active_incidents)
    online_count = total_count - offline_count

    # Always labeling the 4th column as Work Order / Status
    detail_label = "Work Order / Status"
    status_color = "#dc3545" if status == "OFFLINE" else "#28a745"
    subject = f"{'🚨' if status == 'OFFLINE' else '✅'} NRC-1 CCTV Report: {status}"

    table_rows = ""
    for cam in cam_list:
        # Check if individual camera is online or offline for color coding
        row_status_color = "#28a745" if "RECOVERED" in str(cam.get('detail', '')) else "#dc3545"
        
        table_rows += f"""
        <tr>
            <td style="border: 1px solid #eee; padding: 10px;">{cam.get('asset', 'Site-Asset')}</td>
            <td style="border: 1px solid #eee; padding: 10px;"><b>{cam['name']}</b></td>
            <td style="border: 1px solid #eee; padding: 10px;">{cam['location']}</td>
            <td style="border: 1px solid #eee; padding: 10px; color: {row_status_color}; font-weight: bold;">{cam['detail']}</td>
        </tr>
        """

    html = f"""
    <html>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #f4f7f6; padding: 20px;">
        <div style="max-width: 700px; margin: auto; background: white; padding: 25px; border-radius: 12px; border: 1px solid #e1e4e8;">
            <h2 style="color: #2c3e50; margin-bottom: 5px;">NRC-1 CCTV Status Dashboard</h2>
            <p style="color: #7f8c8d; font-size: 14px; margin-bottom: 25px;">Report Status: {status} | {datetime.now().strftime('%H:%M:%S')}</p>
            <table width="100%" cellspacing="10" cellpadding="0" style="margin-bottom: 20px;">
                <tr>
                    <td width="33%" style="background: #ffffff; border: 1px solid #dee2e6; border-radius: 8px; padding: 15px; text-align: center;">
                        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">TOTAL UNITS</div>
                        <div style="font-size: 24px; font-weight: bold;">{total_count}</div>
                    </td>
                    <td width="33%" style="background: #ffffff; border: 1px solid #dee2e6; border-top: 4px solid #28a745; border-radius: 8px; padding: 15px; text-align: center;">
                        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">ONLINE</div>
                        <div style="font-size: 24px; font-weight: bold; color: #28a745;">{online_count}</div>
                    </td>
                    <td width="33%" style="background: #ffffff; border: 1px solid #dee2e6; border-top: 4px solid #dc3545; border-radius: 8px; padding: 15px; text-align: center;">
                        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">OFFLINE</div>
                        <div style="font-size: 24px; font-weight: bold; color: #dc3545;">{offline_count:02d}</div>
                    </td>
                </tr>
            </table>
            <table width="100%" border="0" cellpadding="0" style="border-collapse: collapse; font-size: 13px; border: 1px solid #eee;">
                <tr style="background-color: #5dade2; color: white; text-align: left;">
                    <th style="padding: 12px; border: 1px solid #eee;">Asset Location</th>
                    <th style="padding: 12px; border: 1px solid #eee;">Camera #</th>
                    <th style="padding: 12px; border: 1px solid #eee;">Area</th>
                    <th style="padding: 12px; border: 1px solid #eee;">{detail_label}</th>
                </tr>
                {table_rows}
            </table>
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
        print(f"📧 Email Sent: {status}")
    except Exception as e: print(f"❌ Mail Error: {e}")

# --- 3. MONITORING & COMMANDS ---

def check_for_commands():
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, params={"offset": -1}, timeout=5).json()
        if resp["result"]:
            text = resp["result"][-1].get("message", {}).get("text", "").strip().lower()
            if text == "/mailit":
                handle_mailit(hard=False)
            elif text == "/hardmailit":
                handle_mailit(hard=True)
    except: pass

def handle_mailit(hard=False):
    devices = load_device_dict()
    active_incidents = load_active_incidents() # Dictionary {Name: WO}
    
    if not active_incidents:
        send_telegram("ℹ️ No active incidents found to report.")
        return

    # 1. Check live status of all devices
    ips = list(devices.keys())
    with ThreadPoolExecutor(max_workers=20) as executor:
        online_results = list(executor.map(is_online, ips))
    
    # Map status to camera names
    status_map = {devices[ip]['name']: online_results[i] for i, ip in enumerate(ips)}
    any_online = any(online_results)
    all_online = all(online_results)

    # 2. THE GATEKEEPER LOGIC
    if not hard and not all_online:
        send_telegram("❌ Site not fully online. Use <b>/hardmailit</b> for a partial report.")
        return
    
    if hard and not any_online:
        send_telegram("⚠️ <b>Process Aborted:</b> At least one camera must be online to send a Hard Mail Report.")
        return

    # 3. START PROCESSING
    final_batch = []
    updated_incidents = active_incidents.copy()

    # If it's a hardmailit but everyone is online, treat it as a clean recovery
    report_label = "SITE RECOVERY" if all_online else "PARTIAL RECOVERY"
    send_telegram(f"📧 Generating {report_label}...")

    for cam_name, original_wo in active_incidents.items():
        cam_obj = next((c for c in devices.values() if c['name'] == cam_name), None)
        if not cam_obj: continue

        if status_map.get(cam_name):
            # Camera is back online
            send_telegram(f"📝 Reason for <b>{cam_name}</b>?")
            reason = get_telegram_reply(cam_name, "Reason")
            cam_obj['detail'] = f"RECOVERED: {reason}"
            final_batch.append(cam_obj)
            del updated_incidents[cam_name] 
        else:
            # Camera still offline (Only happens in /hardmailit)
            cam_obj['detail'] = f"PENDING (WO: {original_wo})"
            final_batch.append(cam_obj)

    send_batch_dashboard_email(final_batch, report_label)
    save_active_incidents(updated_incidents)
    send_telegram(f"✅ {report_label} Sent. Incident list updated.")

def run_monitor():
    global last_state, pending_offline, pending_recovery
    devices = load_device_dict()
    active_incidents = load_active_incidents()
    ips = list(devices.keys())
    now_ts = time.time()
    
    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(is_online, ips))

    batch_offline = []

    for i, ip in enumerate(ips):
        online = results[i]
        cam = devices[ip]
        name = cam['name']
        if ip not in last_state: last_state[ip] = True

        if not online:
            if ip in pending_recovery: del pending_recovery[ip]
            # If cam is offline but not already in the "Incident List"
            if last_state[ip] and name not in active_incidents: 
                if ip not in pending_offline:
                    pending_offline[ip] = now_ts
                elif (now_ts - pending_offline[ip]) >= OFFLINE_THRESHOLD:
                    last_state[ip] = False
                    batch_offline.append(cam)
                    del pending_offline[ip]
        else:
            if not last_state[ip]:
                if ip not in pending_recovery:
                    pending_recovery[ip] = now_ts
                elif (now_ts - pending_recovery[ip]) >= RECOVERY_STABILITY:
                    last_state[ip] = True
                    send_telegram(f"✅ {name} is now STABLE. (Wait for /mailit)")
                    del pending_recovery[ip]
            if ip in pending_offline: del pending_offline[ip]

    if batch_offline:
        send_telegram(f"🚨 {len(batch_offline)} CAMS DOWN. Provide Work Orders:")
        for cam in batch_offline:
            send_telegram(f"🔹 <b>{cam['name']}</b>\nType WO:")
            wo = get_telegram_reply(cam['name'], "Work Order")
            cam['detail'] = wo
            active_incidents[cam['name']] = wo # Map Name to WO
        
        save_active_incidents(active_incidents)
        send_batch_dashboard_email(batch_offline, "OFFLINE")
        send_telegram("✅ Offline Report Sent.")

if __name__ == "__main__":
    print("\n🚀 NRC-1 DASHBOARD ONLINE (HARDMAILIT ENABLED)")
    send_telegram("🚀 <b>NRC-1 MONITORING ONLINE</b>\nCommands: /mailit, /hardmailit")
    
    while True:
        run_monitor()
        check_for_commands()
        time.sleep(20)
