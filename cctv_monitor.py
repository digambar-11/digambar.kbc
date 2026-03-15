import subprocess, platform, time, requests, sqlite3, os, smtplib, threading, sys, csv, shutil, configparser
import tkinter as tk
import tkinter.scrolledtext as st
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor

# ==============================================================================
# VISUAL THEME CONFIG
# ==============================================================================
PRIMARY_BG = "#0f172a"
CARD_BG = "#1e293b"
HEADER_BG = "#020617"
HEADER_FG = "#e5e7eb"
TEXT_PRIMARY = "#f8fafc"
TEXT_MUTED = "#94a3b8"
BORDER_COLOR = "#334155"
ACCENT_BLUE = "#3b82f6"
ACCENT_RED = "#ef4444"
ACCENT_GREEN = "#22c55e"
ACCENT_ORANGE = "#ea580c"
FONT_FAMILY = "Segoe UI"

# ==============================================================================
# SECURITY CONFIGURATION
# ==============================================================================
config = configparser.ConfigParser()
if not os.path.exists('config.ini'):
    print("❌ ERROR: config.ini not found!")
    sys.exit()

try:
    config.read('config.ini')
    TELE_TOKEN = config['SECRETS']['TELE_TOKEN']
    EMAIL_PASSWORD = config['SECRETS']['EMAIL_PASSWORD']
    CHAT_ID_CCTV = config['SECRETS']['ADMIN_TELEGRAM_ID']
    ADMIN_ID = config['SECRETS']['ADMIN_TELEGRAM_ID']
    GATEWAY_IP = config.get('SECRETS', 'GATEWAY_IP', fallback='192.168.1.1')
except KeyError as e:
    print(f"❌ ERROR: Missing key in config.ini: {e}")
    sys.exit()

DB_NAME = "cctv_manager.db"
LOG_FILE = "downtime_report.csv"
EMAIL_SENDER = "digambarkokitkar11@gmail.com"
TO_EMAILS = ["digambarkokitkar11@gmail.com"]
CC_EMAILS = ["kokitkardigamber11@gmail.com"]
SMTP_SERVER, SMTP_PORT = "smtp.gmail.com", 587

# Global State (single declaration)
LAST_TELE_ID = 0
RECOVERY_TRACKER = {}
ACTIVE_PROMPTS = {}
REPORT_SENT_DATE = None
GATEWAY_REACHABLE = True
WO_INPUT_PAUSE = False
WO_QUEUE = []
COMMENT_QUEUE = []
OFFLINE_WINDOW = None
OFFLINE_WINDOW_TEXT = None

# ==============================================================================
# DATABASE LAYER
# ==============================================================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS cameras (
        ip TEXT PRIMARY KEY,
        name TEXT,
        location TEXT,
        status INTEGER DEFAULT 1,
        last_change TEXT DEFAULT 'Never',
        mail_eligible INTEGER DEFAULT 0,
        work_order TEXT DEFAULT NULL,
        comment TEXT DEFAULT NULL,
        down_time TEXT DEFAULT NULL,
        recovered_time TEXT DEFAULT NULL,
        downtime_duration TEXT DEFAULT NULL,
        maintenance_mode INTEGER DEFAULT 0,
        incident_id TEXT DEFAULT NULL
    )''')

    required_columns = {
        'mail_eligible': 'INTEGER DEFAULT 0',
        'work_order': 'TEXT DEFAULT NULL',
        'comment': 'TEXT DEFAULT NULL',
        'down_time': 'TEXT DEFAULT NULL',
        'recovered_time': 'TEXT DEFAULT NULL',
        'downtime_duration': 'TEXT DEFAULT NULL',
        'maintenance_mode': 'INTEGER DEFAULT 0',
        'incident_id': 'TEXT DEFAULT NULL',
    }

    cursor.execute("PRAGMA table_info(cameras)")
    existing_cols = [col[1] for col in cursor.fetchall()]
    for col_name, col_type in required_columns.items():
        if col_name not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE cameras ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

    conn.commit()
    conn.close()

def query_db(query, params=(), commit=False):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(query, params)
        if commit:
            conn.commit()
        res = cursor.fetchall()
        conn.close()
        return res
    except Exception as e:
        print(f"DB Error: {e}")
        return []

def backup_database():
    try:
        if not os.path.exists("backups"):
            os.makedirs("backups")
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        shutil.copy2(DB_NAME, f"backups/backup_{ts}.db")
        update_gui_console("💾 DB Backup created successfully.", "info")
    except Exception as e:
        update_gui_console(f"⚠️ Backup failed: {e}", "error")

# ==============================================================================
# INCIDENT QUERIES — FIXED
# ==============================================================================
def get_pending_wo_cameras():
    """Mail-eligible cameras with NO work order assigned."""
    return query_db(
        """SELECT ip, name, location, down_time, work_order, comment
           FROM cameras
           WHERE mail_eligible = 1
           AND (work_order IS NULL OR work_order = '' OR work_order = 'NOT_PROVIDED')
           AND maintenance_mode = 0
           ORDER BY down_time ASC"""
    )

def get_pending_comment_cameras():
    """Recovered mail-eligible cameras with WO assigned but no comment yet."""
    return query_db(
        """SELECT ip, name, location, down_time, work_order, comment
           FROM cameras
           WHERE mail_eligible = 1
           AND status = 1
           AND work_order IS NOT NULL AND work_order != '' AND work_order != 'NOT_PROVIDED'
           AND (comment IS NULL OR comment = '')
           AND maintenance_mode = 0
           ORDER BY down_time ASC"""
    )

# ==============================================================================
# LOGGING
# ==============================================================================
def log_to_csv(event_type, name, ip, location, duration="N/A", wo="N/A", comment="N/A", incident_id="N/A"):
    file_exists = os.path.isfile(LOG_FILE)
    try:
        with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Timestamp", "IncidentID", "Event", "Name", "IP", "Location", "Downtime", "WO", "Comment"])
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                incident_id, event_type, name, ip, location, duration, wo, comment
            ])
    except Exception as e:
        print(f"CSV log error: {e}")

def cleanup_old_logs(days=90):
    if not os.path.exists(LOG_FILE):
        return
    cutoff = datetime.now() - timedelta(days=days)
    rows = []
    try:
        with open(LOG_FILE, 'r') as f:
            r = csv.reader(f)
            h = next(r)
            for row in r:
                try:
                    if datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S') > cutoff:
                        rows.append(row)
                except:
                    pass
        with open(LOG_FILE, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(h)
            w.writerows(rows)
    except:
        pass

# ==============================================================================
# PING
# ==============================================================================
def is_online(ip):
    is_win = platform.system().lower() == 'windows'
    param = '-n' if is_win else '-c'
    timeout = '2000' if is_win else '1'
    si = None
    if is_win:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        res = subprocess.run(
            ['ping', param, '1', '-w', timeout, ip],
            capture_output=True, text=True, timeout=2,
            startupinfo=si,
            creationflags=0x08000000 if is_win else 0
        )
        return "TTL=" in res.stdout
    except:
        return False

# ==============================================================================
# EMAIL — WITH recovered_time COLUMN
# ==============================================================================
def _format_down_time(down_time_str):
    if not down_time_str:
        return "—"
    try:
        dt = datetime.strptime(down_time_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d %b %Y, %H:%M")
    except:
        return down_time_str

def send_daily_report():
    all_stats = query_db("SELECT status FROM cameras WHERE maintenance_mode = 0")
    if not all_stats:
        update_gui_console("⚠️ Report Aborted: No cameras found.", "error")
        return

    total_assets = len(all_stats)
    online_count = sum(1 for x in all_stats if x[0] == 1)
    offline_count = total_assets - online_count
    uptime_pct = round((online_count / total_assets * 100), 1) if total_assets > 0 else 0

    incident_data = query_db(
        "SELECT name, location, status, work_order, comment, down_time, downtime_duration, recovered_time "
        "FROM cameras WHERE mail_eligible=1"
    )

    now = datetime.now()
    report_date = now.strftime("%d %b %Y")
    gateway_status = "Healthy" if GATEWAY_REACHABLE else "Degraded"

    chart_url = (
        "https://quickchart.io/chart?"
        f"c={{type:'doughnut',data:{{labels:['Online','Offline'],"
        f"datasets:[{{data:[{online_count},{offline_count}],backgroundColor:['%2310b981','%23ef4444'],"
        "borderWidth:3,borderColor:'#fff'}}]}},options:{{responsive:true,plugins:{{legend:{{position:'bottom'}}}}}}}}"
    )

    if not incident_data:
        table_content = (
            "<tr><td colspan='8' style='padding:40px;text-align:center;color:#94a3b8;font-style:italic;'>"
            "No critical incidents recorded.</td></tr>"
        )
    else:
        table_content = ""
        for name, loc, status, wo, comment, down_time, duration, recovered_time in incident_data:
            status_color = "#10b981" if status == 1 else "#ef4444"
            status_bg = "#f0fdf4" if status == 1 else "#fef2f2"
            status_text = "RESOLVED" if status == 1 else "CRITICAL"
            name_clean = (name or "Unknown").strip()
            comment_safe = (comment or "—").replace("<", "&lt;").replace(">", "&gt;")[:85]
            rec_display = _format_down_time(recovered_time) if recovered_time else "Still Offline"
            table_content += f"""
            <tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:14px 10px;font-size:12px;color:#64748b;">{loc or '—'}</td>
                <td style="padding:14px 10px;font-size:13px;color:#1e293b;font-weight:600;">
                    <span style="color:{status_color};margin-right:4px;">●</span>{name_clean}
                </td>
                <td style="padding:14px 10px;font-size:12px;color:#475569;">{_format_down_time(down_time)}</td>
                <td style="padding:14px 10px;font-size:12px;color:#475569;">{rec_display}</td>
                <td style="padding:14px 10px;font-size:12px;color:#475569;font-weight:500;">{duration or 'Ongoing'}</td>
                <td style="padding:14px 10px;font-size:12px;color:#475569;font-family:monospace;">{wo or '—'}</td>
                <td style="padding:14px 10px;font-size:12px;color:#94a3b8;">{comment_safe}</td>
                <td style="padding:14px 10px;text-align:right;">
                    <span style="background:{status_bg};color:{status_color};padding:4px 10px;border-radius:6px;
                    font-size:10px;font-weight:700;border:1px solid {status_color}22;">{status_text}</span>
                </td>
            </tr>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
    <body style="margin:0;padding:30px 0;background:#f8fafc;">
    <div style="width:100%;max-width:760px;margin:0 auto;">
        <div style="background:#0f172a;padding:28px 24px;border-radius:12px 12px 0 0;">
            <h1 style="margin:0;font-size:20px;color:#fff;font-weight:800;">NRC-1 Intelligence</h1>
            <p style="margin:4px 0 0;font-size:12px;color:#94a3b8;">Network Operations · Daily Status Report · {report_date}</p>
        </div>
        <div style="background:#fff;border:1px solid #e2e8f0;">
            <table width="100%" cellspacing="0" cellpadding="0" style="border-bottom:1px solid #f1f5f9;">
                <tr>
                    <td width="33%" style="padding:20px;text-align:center;border-right:1px solid #f1f5f9;">
                        <div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;margin-bottom:6px;">Reachability</div>
                        <div style="font-size:26px;font-weight:800;color:#0f172a;">{uptime_pct}%</div>
                    </td>
                    <td width="33%" style="padding:20px;text-align:center;border-right:1px solid #f1f5f9;">
                        <div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;margin-bottom:6px;">Online</div>
                        <div style="font-size:26px;font-weight:800;color:#10b981;">{online_count} <span style="font-size:13px;color:#94a3b8;">/ {total_assets}</span></div>
                    </td>
                    <td width="33%" style="padding:20px;text-align:center;">
                        <div style="font-size:10px;font-weight:700;color:#dc2626;text-transform:uppercase;margin-bottom:6px;">Critical</div>
                        <div style="font-size:26px;font-weight:800;color:#ef4444;">{offline_count}</div>
                    </td>
                </tr>
            </table>
            <div style="padding:20px;text-align:center;">
                <img src="{chart_url}" width="200" alt="Health Chart">
            </div>
            <div style="padding:20px;">
                <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
                    <thead>
                        <tr style="background:#f8fafc;">
                            <th style="padding:10px;text-align:left;font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;">Location</th>
                            <th style="padding:10px;text-align:left;font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;">Asset</th>
                            <th style="padding:10px;text-align:left;font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;">Offline Time</th>
                            <th style="padding:10px;text-align:left;font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;">Recovered</th>
                            <th style="padding:10px;text-align:left;font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;">Duration</th>
                            <th style="padding:10px;text-align:left;font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;">W.O.</th>
                            <th style="padding:10px;text-align:left;font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;">Notes</th>
                            <th style="padding:10px;text-align:right;font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;">Status</th>
                        </tr>
                    </thead>
                    <tbody>{table_content}</tbody>
                </table>
            </div>
            <div style="background:#f1f5f9;padding:16px 24px;border-radius:0 0 12px 12px;">
                <span style="font-size:11px;color:#64748b;"><b>Gateway:</b> {GATEWAY_IP} | <b>Status:</b> {gateway_status}</span>
                <span style="float:right;font-size:11px;color:#94a3b8;">NRC-1 V6.3 Engine</span>
            </div>
        </div>
    </div>
    </body></html>"""

    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = ", ".join(TO_EMAILS)
        msg['Cc'] = ", ".join(CC_EMAILS)
        msg['Subject'] = f"📊 Daily CCTV Report - {datetime.now().strftime('%d %b %Y')}"
        msg.attach(MIMEText(html, 'html'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, TO_EMAILS + CC_EMAILS, msg.as_string())
        server.quit()
        update_gui_console("✅ Daily report sent successfully.", "success")
    except Exception as e:
        error_msg = f"❌ Daily report FAILED: {str(e)}"
        update_gui_console(error_msg, "error")
        try:
            send_telegram(f"🚨 <b>Daily Report Email FAILED</b>\n<b>Error:</b> {str(e)}")
        except:
            pass

# ==============================================================================
# TELEGRAM
# ==============================================================================
def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID_CCTV, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except:
        pass

def broadcast_system_state(message):
    update_gui_console(message, "action")
    send_telegram(message)

# ==============================================================================
# GUI UTILITIES
# ==============================================================================
def update_gui_console(text, tag="info"):
    def _w():
        console_box.config(state='normal')
        ts = datetime.now().strftime('%H:%M:%S')
        console_box.insert(tk.END, f"[{ts}] ", "time")
        console_box.insert(tk.END, f"{text}\n", tag)
        console_box.see(tk.END)
        console_box.config(state='disabled')
    root.after(0, _w)

def update_status_bar(total, online, offline, muted):
    root.after(0, lambda: [
        lbl_total.config(text=str(total)),
        lbl_online.config(text=str(online)),
        lbl_offline.config(text=str(offline)),
        lbl_muted.config(text=str(muted))
    ])

# ==============================================================================
# COMMANDS — ALL BUGS FIXED
# ==============================================================================
def process_command(raw, src="GUI"):
    if not raw or not raw.strip():
        return
    parts = raw.strip().split(" ", 1)
    cmd = parts[0].lower()
    val = parts[1].strip() if len(parts) > 1 else None
    now = datetime.now()
    in_4_9_window = (4 <= now.hour < 9)  # FIX: was inverted before

    # ── /mute ──
    if cmd == "/mute":
        if not val:
            msg = "Usage: /mute <ip>"
            update_gui_console(msg, "info"); send_telegram(msg); return
        rows = query_db("SELECT name, ip, location, maintenance_mode FROM cameras WHERE ip=?", (val,))
        if not rows:
            msg = f"❌ No IP address found: {val}"
            update_gui_console(msg, "error"); send_telegram(msg); return
        name, ip, loc, is_muted = rows[0]
        if is_muted == 1:  # FIX: check if already muted
            msg = f"ℹ️ {name} (IP: {ip}) is already muted."
            update_gui_console(msg, "info"); send_telegram(msg); return
        query_db("UPDATE cameras SET maintenance_mode=1 WHERE ip=?", (ip,), commit=True)
        msg = f"🔇 Muted: {name} (IP: {ip}, Loc: {loc})"
        update_gui_console(msg, "action"); send_telegram(msg)

    # ── /unmute ──
    elif cmd == "/unmute":
        if not val:
            msg = "Usage: /unmute <ip>"
            update_gui_console(msg, "info"); send_telegram(msg); return
        rows = query_db("SELECT name, ip, location, maintenance_mode FROM cameras WHERE ip=?", (val,))
        if not rows:
            msg = f"❌ No IP address found: {val}"
            update_gui_console(msg, "error"); send_telegram(msg); return
        name, ip, loc, is_muted = rows[0]
        if is_muted == 0:  # FIX: check if not muted before unmuting
            msg = f"ℹ️ {name} (IP: {ip}) is not muted."
            update_gui_console(msg, "info"); send_telegram(msg); return
        query_db("UPDATE cameras SET maintenance_mode=0 WHERE ip=?", (ip,), commit=True)
        msg = f"🔊 Unmuted: {name} (IP: {ip}, Loc: {loc})"
        update_gui_console(msg, "action"); send_telegram(msg)

    # ── /wo — available 9 AM to 4 AM only ──
    elif cmd == "/wo":
        if in_4_9_window:  # FIX: block DURING 4-9 AM window
            msg = "ℹ️ /wo is not available during the 4–9 AM window. Use the popup instead."
            update_gui_console(msg, "info"); send_telegram(msg); return
        pending = get_pending_wo_cameras()
        if not pending:
            msg = "ℹ️ No cameras pending work order assignment."
            update_gui_console(msg, "info"); send_telegram(msg); return
        if val:
            if not val.isdigit():  # FIX: integer validation
                msg = "❌ Invalid format: Work Order must be numbers only."
                update_gui_console(msg, "error"); send_telegram(msg); return
            if ACTIVE_PROMPTS:
                ips = list(ACTIVE_PROMPTS.keys())[0].split(",")
                finalize_wo(ips, val, src)
            else:
                finalize_wo([pending[0][0]], val, src)
        else:
            if ACTIVE_PROMPTS:
                try: ACTIVE_PROMPTS[list(ACTIVE_PROMPTS.keys())[0]].lift()
                except: pass
                return
            ip, name, loc, down_time, _, _ = pending[0]
            WO_QUEUE.append([ip])
            msg = f"📋 WO prompt queued for {name} (IP: {ip})."
            update_gui_console(msg, "info"); send_telegram(msg)

    # ── /comment — available 9 AM to 4 AM only ──
    elif cmd == "/comment":
        if in_4_9_window:  # FIX: block DURING 4-9 AM window
            msg = "ℹ️ /comment is not available during the 4–9 AM window."
            update_gui_console(msg, "info"); send_telegram(msg); return
        pending = get_pending_comment_cameras()
        if not pending:
            msg = "ℹ️ No recovered cameras pending a comment (or all assigned already)."
            update_gui_console(msg, "info"); send_telegram(msg); return
        if val:
            if ACTIVE_PROMPTS:
                ips = list(ACTIVE_PROMPTS.keys())[0].split(",")
                finalize_comment(ips, val, src)
            else:
                finalize_comment([pending[0][0]], val, src)
        else:
            if ACTIVE_PROMPTS:
                try: ACTIVE_PROMPTS[list(ACTIVE_PROMPTS.keys())[0]].lift()
                except: pass
                return
            ip, name, loc, down_time, wo, _ = pending[0]
            COMMENT_QUEUE.append([ip])
            msg = f"📋 Comment prompt queued for {name} (IP: {ip})."
            update_gui_console(msg, "info"); send_telegram(msg)

    # ── /status ──
    elif cmd == "/status":
        off = query_db("SELECT COUNT(*) FROM cameras WHERE status=0 AND maintenance_mode=0")[0][0]
        on = query_db("SELECT COUNT(*) FROM cameras WHERE status=1 AND maintenance_mode=0")[0][0]
        muted = query_db("SELECT COUNT(*) FROM cameras WHERE maintenance_mode=1")[0][0]
        msg = f"📊 Status — Online: {on} | Offline: {off} | Muted: {muted}"
        update_gui_console(msg, "info"); send_telegram(msg)

    else:
        valid = ["/mute <ip>", "/unmute <ip>", "/wo [number]", "/comment [text]", "/status"]
        msg = f"❌ Unknown command: '{cmd}'\n\nValid commands:\n" + "\n".join(f"• {c}" for c in valid)
        update_gui_console(msg, "error"); send_telegram(msg)

# ==============================================================================
# STARTUP REPAIR — DB/SCRIPT SYNC
# ==============================================================================
def close_stale_open_incidents_on_startup():
    rows = query_db(
        "SELECT ip, name, location, down_time, work_order, comment, incident_id "
        "FROM cameras WHERE status=1 AND incident_id IS NOT NULL"
    )
    if not rows:
        return
    now = datetime.now()
    full_ts = now.strftime('%Y-%m-%d %H:%M:%S')
    for ip, name, loc, down_time, wo, comment, incident_id in rows:
        dur = "N/A"
        if down_time:
            try:
                dur = str(now - datetime.strptime(down_time, '%Y-%m-%d %H:%M:%S')).split('.')[0]
            except:
                pass
        log_to_csv("RECOVERED", name or ip, ip, loc or "N/A",
                   duration=dur, wo=wo or "N/A", comment=comment or "N/A",
                   incident_id=incident_id or "N/A")
        query_db(
            "UPDATE cameras SET last_change=?, recovered_time=?, downtime_duration=?, "
            "mail_eligible=0, work_order=NULL, incident_id=NULL WHERE ip=?",
            (full_ts, full_ts, dur, ip), commit=True
        )
        update_gui_console(f"♻️ Startup sync: closed stale incident for {name or ip}.", "info")

def check_for_backlog():
    backlog = query_db(
        "SELECT ip, name FROM cameras WHERE mail_eligible=1 "
        "AND (work_order IS NULL OR work_order='') AND maintenance_mode=0"
    )
    if backlog:
        update_gui_console(f"📋 Backlog: {len(backlog)} camera(s) pending WO assignment.", "action")

# ==============================================================================
# CURRENT OFFLINE WINDOW
# ==============================================================================
def refresh_current_offline_window():
    global OFFLINE_WINDOW, OFFLINE_WINDOW_TEXT
    if OFFLINE_WINDOW is None or not OFFLINE_WINDOW.winfo_exists():
        OFFLINE_WINDOW = None; OFFLINE_WINDOW_TEXT = None; return
    res = query_db(
        "SELECT name, ip, location, work_order, down_time FROM cameras WHERE status=0 AND maintenance_mode=0"
    )
    OFFLINE_WINDOW_TEXT.config(state='normal')
    OFFLINE_WINDOW_TEXT.delete('1.0', tk.END)
    if not res:
        OFFLINE_WINDOW_TEXT.insert(tk.END, "✅ All critical cameras are online.\n")
    else:
        for name, ip, loc, wo, down_time in res:
            OFFLINE_WINDOW_TEXT.insert(tk.END,
                f"[🔴 OFFLINE] {name}\nIP: {ip} | Loc: {loc}\n"
                f"WO: {wo or 'None'} | Down: {down_time or 'N/A'}\n{'-'*45}\n")
    OFFLINE_WINDOW_TEXT.config(state='disabled')
    root.after(5000, refresh_current_offline_window)

def show_current_offline():
    global OFFLINE_WINDOW, OFFLINE_WINDOW_TEXT
    if OFFLINE_WINDOW is not None and OFFLINE_WINDOW.winfo_exists():
        refresh_current_offline_window(); OFFLINE_WINDOW.lift(); return
    OFFLINE_WINDOW = tk.Toplevel(root)
    OFFLINE_WINDOW.title("Current Offline Cameras")
    OFFLINE_WINDOW.configure(bg=PRIMARY_BG)
    OFFLINE_WINDOW.geometry("580x380")
    tk.Label(OFFLINE_WINDOW, text="Current Offline Cameras", font=(FONT_FAMILY, 11, "bold"),
             bg=PRIMARY_BG, fg=TEXT_PRIMARY, anchor="w").pack(fill="x", padx=14, pady=(12, 4))
    OFFLINE_WINDOW_TEXT = st.ScrolledText(OFFLINE_WINDOW, bg=CARD_BG, fg=TEXT_PRIMARY,
                                           font=("Consolas", 10), relief="flat", borderwidth=1)
    OFFLINE_WINDOW_TEXT.pack(fill="both", expand=True, padx=10, pady=(0, 12))
    refresh_current_offline_window()

def search_camera_gui():
    try:
        val = search_entry.get().strip()
    except:
        return
    if not val:
        return
    res = query_db(
        "SELECT name, ip, location, status, work_order, down_time, maintenance_mode "
        "FROM cameras WHERE name LIKE ? OR ip LIKE ?",
        (f'%{val}%', f'%{val}%')
    )
    win = tk.Toplevel(root)
    win.title(f"Search: {val}")
    win.configure(bg=PRIMARY_BG)
    win.geometry("580x380")
    tk.Label(win, text=f"Search: \"{val}\"", font=(FONT_FAMILY, 11, "bold"),
             bg=PRIMARY_BG, fg=TEXT_PRIMARY, anchor="w").pack(fill="x", padx=14, pady=(12, 4))
    txt = st.ScrolledText(win, bg=CARD_BG, fg=TEXT_PRIMARY, font=("Consolas", 10), relief="flat")
    txt.pack(fill="both", expand=True, padx=10, pady=(0, 12))
    if not res:
        txt.insert(tk.END, "❌ No matching assets found.")
    else:
        for r in res:
            stat = "🟢 ONLINE" if r[3] == 1 else "🔴 OFFLINE"
            maint = " [MUTED]" if r[6] == 1 else ""
            txt.insert(tk.END,
                f"[{stat}]{maint} {r[0]}\nIP: {r[1]} | Loc: {r[2]}\n"
                f"WO: {r[4] or 'None'} | Down: {r[5]}\n{'-'*55}\n")
    txt.config(state="disabled")

# ==============================================================================
# WO INPUT WINDOW
# ==============================================================================
def finalize_wo(ips, wo, src):
    global WO_INPUT_PAUSE
    ph = ','.join(['?'] * len(ips))
    query_db(f"UPDATE cameras SET work_order=? WHERE ip IN ({ph})", (wo, *ips), commit=True)
    msg = f"✅ Work Order {wo} assigned via {src}."
    update_gui_console(msg, "success"); send_telegram(msg)
    ip_k = ",".join(ips)
    if ip_k in ACTIVE_PROMPTS:
        w = ACTIVE_PROMPTS.pop(ip_k)
        root.after(0, w.destroy)
    if not ACTIVE_PROMPTS:
        WO_INPUT_PAUSE = False
        update_gui_console("▶️ Alerts resumed.", "success")

def open_dual_input_window(ips):
    global WO_INPUT_PAUSE
    WO_INPUT_PAUSE = True
    update_gui_console("⏸️ Alerts paused — Enter Work Order. Monitoring continues.", "action")

    rows = query_db(
        f"SELECT name, ip, location, down_time FROM cameras WHERE ip IN ({','.join(['?']*len(ips))})", ips
    )
    detail_lines = []
    for name, ip, loc, down_time in rows:
        down_str = "N/A"
        if down_time:
            try: down_str = datetime.strptime(down_time, "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
            except: down_str = down_time
        detail_lines.append(f"{name} OFFLINE | IP: {ip} | Loc: {loc} | Down: {down_str}")
    if not detail_lines:
        detail_lines = ["Camera(s) are offline."]

    send_telegram("⚠️ <b>WORK ORDER REQUIRED</b>\n" + "\n".join(detail_lines))

    prompt = tk.Toplevel(root)
    prompt.title("Work Order Required")
    prompt.configure(bg=PRIMARY_BG)
    prompt.resizable(False, False)

    def _on_close():
        global WO_INPUT_PAUSE
        ACTIVE_PROMPTS.pop(",".join(ips), None)
        if not ACTIVE_PROMPTS:
            WO_INPUT_PAUSE = False
            update_gui_console("▶️ WO window closed. Alerts resumed.", "info")
        try: prompt.destroy()
        except: pass

    prompt.protocol("WM_DELETE_WINDOW", _on_close)
    tk.Label(prompt, text="⚠️ Work Order Required", font=(FONT_FAMILY, 11, "bold"),
             bg=PRIMARY_BG, fg=ACCENT_RED, anchor="w").pack(fill="x", padx=14, pady=(14, 4))
    tk.Label(prompt, text="\n\n".join(detail_lines), wraplength=460, justify="left",
             fg=TEXT_PRIMARY, bg=PRIMARY_BG, font=(FONT_FAMILY, 9)).pack(padx=14, pady=(0, 10), fill="x")

    ef = tk.Frame(prompt, bg=PRIMARY_BG)
    ef.pack(fill="x", padx=14, pady=(0, 10))
    tk.Label(ef, text="Work Order Number (integers only):", bg=PRIMARY_BG, fg=TEXT_MUTED,
             font=(FONT_FAMILY, 9)).pack(anchor="w")
    wo_var = tk.StringVar()
    tk.Entry(ef, textvariable=wo_var, font=(FONT_FAMILY, 10), bg=CARD_BG, fg=TEXT_PRIMARY,
             insertbackground=TEXT_PRIMARY, relief="flat").pack(fill="x", pady=(2, 0))

    def _submit():
        wo_text = wo_var.get().strip()
        if not wo_text.isdigit():
            update_gui_console("❌ Invalid: Work Order must be numbers only.", "error")
            send_telegram("❌ Invalid: Work Order must be numbers only.")
            return
        finalize_wo(ips, wo_text, "GUI")

    tk.Button(prompt, text="Submit Work Order", command=_submit,
              bg=ACCENT_BLUE, fg="white", activebackground="#1d4ed8",
              relief="flat", padx=10, pady=6).pack(pady=(0, 14))
    ACTIVE_PROMPTS[",".join(ips)] = prompt

# ==============================================================================
# COMMENT INPUT WINDOW
# ==============================================================================
def finalize_comment(ips, comment, src):
    global WO_INPUT_PAUSE
    ph = ','.join(['?'] * len(ips))
    query_db(f"UPDATE cameras SET comment=? WHERE ip IN ({ph})", (comment, *ips), commit=True)
    msg = f"📝 Comment saved via {src}: {comment}"
    update_gui_console(msg, "success"); send_telegram(msg)
    ip_k = ",".join(ips)
    if ip_k in ACTIVE_PROMPTS:
        w = ACTIVE_PROMPTS.pop(ip_k)
        root.after(0, w.destroy)
    if not ACTIVE_PROMPTS:
        WO_INPUT_PAUSE = False
        update_gui_console("▶️ Alerts resumed.", "success")

def open_comment_input_window(ips):
    global WO_INPUT_PAUSE
    WO_INPUT_PAUSE = True
    update_gui_console("⏸️ Alerts paused — Enter Comment. Monitoring continues.", "action")

    rows = query_db(
        f"SELECT name, ip, location, down_time FROM cameras WHERE ip IN ({','.join(['?']*len(ips))})", ips
    )
    detail_lines = []
    for name, ip, loc, down_time in rows:
        down_str = "N/A"
        if down_time:
            try: down_str = datetime.strptime(down_time, "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
            except: down_str = down_time
        detail_lines.append(f"{name} RECOVERED | IP: {ip} | Loc: {loc} | Down: {down_str}")
    if not detail_lines:
        detail_lines = ["Camera(s) are recovered."]

    send_telegram("📝 <b>COMMENT REQUIRED</b>\n" + "\n".join(detail_lines))

    prompt = tk.Toplevel(root)
    prompt.title("Comment Required")
    prompt.configure(bg=PRIMARY_BG)
    prompt.resizable(False, False)

    def _on_close():
        global WO_INPUT_PAUSE
        ACTIVE_PROMPTS.pop(",".join(ips), None)
        if not ACTIVE_PROMPTS:
            WO_INPUT_PAUSE = False
            update_gui_console("▶️ Comment window closed. Alerts resumed.", "info")
        try: prompt.destroy()
        except: pass

    prompt.protocol("WM_DELETE_WINDOW", _on_close)
    tk.Label(prompt, text="📝 Comment Required", font=(FONT_FAMILY, 11, "bold"),
             bg=PRIMARY_BG, fg=ACCENT_GREEN, anchor="w").pack(fill="x", padx=14, pady=(14, 4))
    tk.Label(prompt, text="\n\n".join(detail_lines), wraplength=460, justify="left",
             fg=TEXT_PRIMARY, bg=PRIMARY_BG, font=(FONT_FAMILY, 9)).pack(padx=14, pady=(0, 10), fill="x")

    ef = tk.Frame(prompt, bg=PRIMARY_BG)
    ef.pack(fill="x", padx=14, pady=(0, 10))
    tk.Label(ef, text="Reason / Comment:", bg=PRIMARY_BG, fg=TEXT_MUTED, font=(FONT_FAMILY, 9)).pack(anchor="w")
    comment_var = tk.StringVar()
    tk.Entry(ef, textvariable=comment_var, font=(FONT_FAMILY, 10), bg=CARD_BG, fg=TEXT_PRIMARY,
             insertbackground=TEXT_PRIMARY, relief="flat").pack(fill="x", pady=(2, 0))

    tk.Button(prompt, text="Submit Comment",
              command=lambda: finalize_comment(ips, comment_var.get().strip(), "GUI"),
              bg=ACCENT_GREEN, fg="white", activebackground="#16a34a",
              relief="flat", padx=10, pady=6).pack(pady=(0, 14))
    ACTIVE_PROMPTS[",".join(ips)] = prompt

# ==============================================================================
# QUEUE PROCESSOR
# ==============================================================================
def check_input_queue():
    if WO_QUEUE and not WO_INPUT_PAUSE and not ACTIVE_PROMPTS:
        open_dual_input_window(WO_QUEUE.pop(0))
    elif COMMENT_QUEUE and not WO_INPUT_PAUSE and not ACTIVE_PROMPTS:
        open_comment_input_window(COMMENT_QUEUE.pop(0))
    root.after(3000, check_input_queue)

def auto_close_wo_prompts_at_9am():
    """FIX: Auto-close all WO/comment prompts when 9 AM is reached."""
    global WO_INPUT_PAUSE
    now = datetime.now()
    if now.hour >= 9 and ACTIVE_PROMPTS:
        for k in list(ACTIVE_PROMPTS.keys()):
            try:
                w = ACTIVE_PROMPTS.pop(k)
                root.after(0, w.destroy)
            except:
                pass
        WO_INPUT_PAUSE = False
        update_gui_console("🕘 9 AM reached — WO windows auto-closed. Alerts resumed.", "action")
    root.after(60000, auto_close_wo_prompts_at_9am)

# ==============================================================================
# MONITORING ENGINE — FIXED GROUP DETECTION & ELIGIBILITY
# ==============================================================================
def run_monitor():
    global RECOVERY_TRACKER, WO_INPUT_PAUSE, GATEWAY_REACHABLE

    if not is_online(GATEWAY_IP):
        if GATEWAY_REACHABLE:
            update_gui_console(f"🚨 GATEWAY DOWN ({GATEWAY_IP}). Monitoring paused.", "error")
            send_telegram(f"🚨 <b>CRITICAL: Gateway {GATEWAY_IP} down. Alerts Paused.</b>")
            GATEWAY_REACHABLE = False
        return
    else:
        if not GATEWAY_REACHABLE:
            update_gui_console("✅ Gateway restored. Resuming monitor.", "success")
            send_telegram("✅ <b>Network Restored. Resuming Camera Monitor.</b>")
            GATEWAY_REACHABLE = True

    cams = query_db(
        "SELECT ip, name, status, down_time, mail_eligible, location, "
        "maintenance_mode, work_order, comment, incident_id FROM cameras"
    )
    if not cams:
        return

    with ThreadPoolExecutor(max_workers=200) as ex:
        results = list(ex.map(is_online, [c[0] for c in cams]))

    now = datetime.now()
    full_ts = now.strftime('%Y-%m-%d %H:%M:%S')
    ts = now.strftime('%H:%M:%S')
    in_mail_window = (4 <= now.hour < 9)

    # FIX: Group detection BEFORE the loop — prevents duplicate/overwritten incident_ids
    newly_offline_indices = [
        i for i, (ip, name, old_stat, *_) in enumerate(cams)
        if not results[i] and old_stat == 1 and cams[i][6] == 0  # exclude muted
    ]
    if len(newly_offline_indices) > 1:
        group_incident_id = f"GROUP-{int(now.timestamp())}"
        group_ips_set = {cams[i][0] for i in newly_offline_indices}
    else:
        group_incident_id = None
        group_ips_set = set()

    on_cnt, off_cnt, muted_cnt = 0, 0, 0
    cur_eligible_grp = []  # cameras newly becoming mail-eligible this cycle

    for i, (ip, name, old_stat, db_dt, is_el, loc, is_mut, wo, comment, incident_id) in enumerate(cams):
        new_stat = 1 if results[i] else 0

        # Always count for status bar (muted included)
        if is_mut == 1:
            muted_cnt += 1
            if new_stat == 1:
                on_cnt += 1
            else:
                off_cnt += 1
            continue  # Skip alerts and incident processing for muted cameras

        if new_stat == 1:
            on_cnt += 1
        else:
            off_cnt += 1

        # ── CAMERA WENT OFFLINE ──
        if new_stat == 0 and old_stat == 1:
            inc_id = group_incident_id if ip in group_ips_set else f"{ip}-{int(now.timestamp())}"
            detail_msg = f"🔴 OFFLINE | {name} | IP: {ip} | Loc: {loc} | Time: {ts} | Inc: {inc_id}"
            update_gui_console(detail_msg, "error")
            if not WO_INPUT_PAUSE:
                send_telegram(f"<b>{detail_msg}</b>")
            query_db(
                "UPDATE cameras SET status=0, last_change=?, down_time=?, incident_id=? WHERE ip=?",
                (full_ts, full_ts, inc_id, ip), commit=True
            )
            log_to_csv("OFFLINE", name, ip, loc, wo=wo or "N/A",
                       comment=comment or "N/A", incident_id=inc_id)
            if ip in RECOVERY_TRACKER:
                del RECOVERY_TRACKER[ip]

        # ── CAMERA RECOVERED — instant alert ──
        elif new_stat == 1 and old_stat == 0:
            if ip not in RECOVERY_TRACKER:
                detail_msg = f"🟢 RECOVERED | {name} | IP: {ip} | Loc: {loc} | Time: {ts}"
                update_gui_console(detail_msg, "success")
                if not WO_INPUT_PAUSE:
                    send_telegram(f"<b>{detail_msg}</b>")
                query_db("UPDATE cameras SET status=1, last_change=? WHERE ip=?", (full_ts, ip), commit=True)
                RECOVERY_TRACKER[ip] = now

            # ── 20-MIN STABILITY CHECK ──
            elif (now - RECOVERY_TRACKER[ip]).total_seconds() / 60 >= 20:
                dur = "N/A"
                if db_dt:
                    try:
                        dur = str(now - datetime.strptime(db_dt, '%Y-%m-%d %H:%M:%S')).split('.')[0]
                    except:
                        pass

                log_to_csv("RECOVERED_STABLE", name, ip, loc, duration=dur,
                           wo=wo or "N/A", comment=comment or "N/A",
                           incident_id=incident_id or "N/A")

                # FIX: If mail_eligible and recovered BEFORE 9 AM → silent reset, no WO needed
                if is_el and in_mail_window:
                    query_db(
                        "UPDATE cameras SET last_change=?, recovered_time=?, downtime_duration=?, "
                        "mail_eligible=0, work_order=NULL, incident_id=NULL WHERE ip=?",
                        (full_ts, full_ts, dur, ip), commit=True
                    )
                    update_gui_console(
                        f"✅ {name} recovered & stable before 9 AM — silent reset, no WO required.", "success"
                    )
                else:
                    query_db(
                        "UPDATE cameras SET status=1, last_change=?, recovered_time=?, "
                        "downtime_duration=?, incident_id=NULL WHERE ip=?",
                        (full_ts, full_ts, dur, ip), commit=True
                    )

                del RECOVERY_TRACKER[ip]

                # Close any open WO/comment prompt for this recovered camera
                for k in list(ACTIVE_PROMPTS.keys()):
                    if ip in k.split(','):
                        w = ACTIVE_PROMPTS.pop(k)
                        root.after(0, w.destroy)

        # ── MAIL ELIGIBILITY — FIX: handles pre-4AM offline cameras too ──
        if new_stat == 0 and not is_el and db_dt:
            try:
                offline_since = datetime.strptime(db_dt, '%Y-%m-%d %H:%M:%S')
                offline_mins = (now - offline_since).total_seconds() / 60
                # Eligible if: 4-9 AM window AND offline for 20+ mins
                # (This covers cameras that went offline before 4 AM and are still offline)
                if in_mail_window and offline_mins >= 20:
                    query_db("UPDATE cameras SET mail_eligible=1 WHERE ip=?", (ip,), commit=True)
                    cur_eligible_grp.append(ip)
                    update_gui_console(f"📋 {name} (IP: {ip}) is now mail eligible.", "action")
            except:
                pass

    # Status bar
    update_status_bar(len(cams), on_cnt, off_cnt, muted_cnt)

    # Add newly eligible cameras to WO queue
    if cur_eligible_grp:
        if len(cur_eligible_grp) > 1:
            # Group failure → single WO prompt for all
            WO_QUEUE.append(cur_eligible_grp)
        else:
            WO_QUEUE.append(cur_eligible_grp)

    # Close WO windows for cameras that got muted after being queued
    for prompt_key in list(ACTIVE_PROMPTS.keys()):
        for ip in prompt_key.split(','):
            rows = query_db("SELECT maintenance_mode FROM cameras WHERE ip=?", (ip,))
            if rows and rows[0][0] == 1:
                w = ACTIVE_PROMPTS.pop(prompt_key, None)
                if w:
                    root.after(0, w.destroy)
                if not ACTIVE_PROMPTS:
                    WO_INPUT_PAUSE = False
                update_gui_console(f"🔇 {ip} muted — WO window closed.", "info")
                send_telegram(f"🔇 Camera {ip} muted — WO window closed.")
                break

# ==============================================================================
# MASTER LOOP
# ==============================================================================
def master_loop():
    global REPORT_SENT_DATE, WO_INPUT_PAUSE
    init_db()
    close_stale_open_incidents_on_startup()
    check_for_backlog()

    broadcast_system_state("🚦 NRC-1 CCTV Master Console starting. Warming up...")
    time.sleep(10)
    broadcast_system_state("⚙️ Initializing core modules. Please wait...")
    time.sleep(10)
    update_gui_console("🚀 NRC-1 CCTV Master Console ONLINE.", "success")
    send_telegram("🚀 <b>System ONLINE. Monitoring activated.</b>")

    while True:
        try:
            run_monitor()
        except Exception as e:
            update_gui_console(f"⚠️ Monitor cycle error: {e}", "error")

        now = datetime.now()

        # Daily report at 9 AM (runs once per day)
        if now.hour >= 9 and REPORT_SENT_DATE != now.date():
            for k in list(ACTIVE_PROMPTS.keys()):
                try:
                    w = ACTIVE_PROMPTS.pop(k)
                    root.after(0, w.destroy)
                except:
                    pass
            WO_INPUT_PAUSE = False
            send_daily_report()
            backup_database()
            cleanup_old_logs()
            REPORT_SENT_DATE = now.date()
            update_gui_console("✅ Daily tasks complete. Normal monitoring resumed.", "success")

        time.sleep(30)

# ==============================================================================
# TELEGRAM POLLER
# ==============================================================================
def telegram_poller():
    global LAST_TELE_ID
    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates",
                params={"offset": LAST_TELE_ID + 1, "timeout": 20}
            ).json()
            if resp.get("result"):
                for up in resp["result"]:
                    LAST_TELE_ID = up["update_id"]
                    m = up.get("message")
                    if m and str(m.get("from", {}).get("id")) == ADMIN_ID:
                        process_command(m.get("text", ""), src="TELEGRAM")
        except:
            pass
        time.sleep(2)

def graceful_shutdown():
    try:
        update_gui_console("🛑 System stopping. Monitoring halted.", "action")
        send_telegram("🛑 <b>System STOPPED. Monitoring halted.</b>")
    except:
        pass
    finally:
        root.destroy()

# ==============================================================================
# GUI SETUP
# ==============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    root.title("NRC-1 CCTV MASTER CONSOLE V6.3")
    root.geometry("900x820")
    root.configure(bg=PRIMARY_BG)
    root.minsize(800, 600)

    # Header
    header = tk.Frame(root, bg=HEADER_BG, height=56)
    header.pack(fill="x", side="top")
    header.pack_propagate(False)
    title_f = tk.Frame(header, bg=HEADER_BG)
    title_f.pack(side="left", padx=20, pady=12)
    tk.Label(title_f, text="●", font=(FONT_FAMILY, 14), bg=HEADER_BG, fg=ACCENT_ORANGE).pack(side="left", padx=(0, 8))
    tk.Label(title_f, text="NRC-1 CCTV", font=(FONT_FAMILY, 14, "bold"), bg=HEADER_BG, fg=HEADER_FG).pack(side="left")
    tk.Label(title_f, text="  MASTER CONSOLE V6.3", font=(FONT_FAMILY, 10), bg=HEADER_BG, fg=TEXT_MUTED).pack(side="left")
    tk.Label(header, text=f"Gateway: {GATEWAY_IP}", font=(FONT_FAMILY, 10), bg=HEADER_BG, fg=TEXT_MUTED).pack(side="right", padx=20)

    # Content
    content = tk.Frame(root, bg=PRIMARY_BG)
    content.pack(fill="both", expand=True, padx=20, pady=(16, 12))

    welcome_f = tk.Frame(content, bg=PRIMARY_BG)
    welcome_f.pack(fill="x", pady=(0, 16))
    tk.Label(welcome_f, text="System Dashboard", font=(FONT_FAMILY, 18, "bold"),
             bg=PRIMARY_BG, fg=HEADER_FG).pack(anchor="w")
    tk.Label(welcome_f, text="Real-time telemetry and incident management",
             font=(FONT_FAMILY, 11), bg=PRIMARY_BG, fg=TEXT_MUTED).pack(anchor="w")

    # Search row
    search_f = tk.Frame(content, bg=PRIMARY_BG)
    search_f.pack(fill="x", pady=(0, 12))
    tk.Label(search_f, text="Search Assets:", font=(FONT_FAMILY, 10),
             bg=PRIMARY_BG, fg=TEXT_MUTED).pack(side="left", padx=(0, 8))
    search_entry = tk.Entry(search_f, font=(FONT_FAMILY, 10), bg=CARD_BG, fg=TEXT_PRIMARY,
                             insertbackground=TEXT_PRIMARY, relief="flat")
    search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
    search_entry.bind("<Return>", lambda e: search_camera_gui())
    tk.Button(search_f, text="Find", command=search_camera_gui, bg=ACCENT_BLUE, fg="white",
              activebackground="#1d4ed8", relief="flat", padx=10, pady=3).pack(side="left")

    # KPI Cards
    kpi_f = tk.Frame(content, bg=PRIMARY_BG)
    kpi_f.pack(fill="x", pady=(0, 20))

    def create_premium_card(parent, title, color):
        card = tk.Frame(parent, bg=BORDER_COLOR, padx=1, pady=1)
        card.pack(side="left", fill="both", expand=True, padx=(0, 10))
        inner = tk.Frame(card, bg=CARD_BG, padx=15, pady=15)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=title.upper(), font=(FONT_FAMILY, 8, "bold"),
                 bg=CARD_BG, fg=TEXT_MUTED).pack(anchor="w")
        lbl = tk.Label(inner, text="-", font=(FONT_FAMILY, 24, "bold"), bg=CARD_BG, fg=TEXT_PRIMARY)
        lbl.pack(anchor="w", pady=(5, 0))
        bar_bg = tk.Frame(inner, bg=BORDER_COLOR, height=2)
        bar_bg.pack(fill="x", pady=(10, 0))
        tk.Frame(bar_bg, bg=color, height=2).place(relx=0, rely=0, relwidth=1.0)
        return lbl

    lbl_total  = create_premium_card(kpi_f, "Network Assets", ACCENT_BLUE)
    lbl_online = create_premium_card(kpi_f, "Uptime Status",  ACCENT_GREEN)
    lbl_offline= create_premium_card(kpi_f, "Critical Alerts",ACCENT_RED)
    lbl_muted  = create_premium_card(kpi_f, "Maintenance",    ACCENT_ORANGE)

    # Main content row
    main_row = tk.Frame(content, bg=PRIMARY_BG)
    main_row.pack(fill="both", expand=True, pady=(0, 12))

    log_card = tk.Frame(main_row, bg=BORDER_COLOR, padx=1, pady=1)
    log_card.pack(side="left", fill="both", expand=True, padx=(0, 12))
    log_inner = tk.Frame(log_card, bg=CARD_BG, padx=12, pady=12)
    log_inner.pack(fill="both", expand=True)
    tk.Label(log_inner, text="SYSTEM TELEMETRY LOG", font=(FONT_FAMILY, 9, "bold"),
             bg=CARD_BG, fg=ACCENT_BLUE).pack(anchor="w")
    console_box = st.ScrolledText(log_inner, bg="#020617", fg=TEXT_PRIMARY, font=("Consolas", 10),
                                   relief="flat", borderwidth=0, insertbackground=TEXT_PRIMARY,
                                   highlightthickness=0)
    console_box.pack(fill="both", expand=True, pady=(8, 0))
    console_box.tag_config("error",   foreground="#f87171")
    console_box.tag_config("success", foreground="#4ade80")
    console_box.tag_config("time",    foreground="#94a3b8")
    console_box.tag_config("action",  foreground="#fbbf24")
    console_box.config(state="disabled")

    # Right column
    right_col = tk.Frame(main_row, bg=PRIMARY_BG, width=260)
    right_col.pack(side="right", fill="y")
    right_col.pack_propagate(False)
    tk.Label(right_col, text="Quick Actions", font=(FONT_FAMILY, 11, "bold"),
             bg=PRIMARY_BG, fg=HEADER_FG).pack(anchor="w", pady=(0, 10))

    actions_card = tk.Frame(right_col, bg=BORDER_COLOR, padx=1, pady=1)
    actions_card.pack(fill="x", pady=(0, 12))
    actions_inner = tk.Frame(actions_card, bg=CARD_BG, padx=12, pady=12)
    actions_inner.pack(fill="x")

    tk.Label(actions_inner, text="COMMAND INPUT", font=(FONT_FAMILY, 8, "bold"),
             bg=CARD_BG, fg=TEXT_MUTED).pack(anchor="w")
    cmd_entry = tk.Entry(actions_inner, font=(FONT_FAMILY, 10), bg=PRIMARY_BG, fg=TEXT_PRIMARY,
                          insertbackground=TEXT_PRIMARY, relief="flat")
    cmd_entry.pack(fill="x", pady=(6, 12))
    cmd_entry.bind("<Return>", lambda e: [process_command(cmd_entry.get(), "GUI"), cmd_entry.delete(0, tk.END)])

    btn_style = {"font": (FONT_FAMILY, 9), "relief": "flat", "cursor": "hand2", "pady": 6, "anchor": "w", "padx": 10}
    tk.Button(actions_inner, text="📊 Current Offline Assets", bg=ACCENT_ORANGE, fg="white",
              command=show_current_offline, **btn_style).pack(fill="x", pady=4)
    tk.Button(actions_inner, text="🔍 System Status (/status)", bg=BORDER_COLOR, fg=TEXT_PRIMARY,
              command=lambda: process_command("/status", "GUI"), **btn_style).pack(fill="x", pady=4)
    tk.Button(actions_inner, text="📋 Work Orders (/wo)", bg=BORDER_COLOR, fg=TEXT_PRIMARY,
              command=lambda: process_command("/wo", "GUI"), **btn_style).pack(fill="x", pady=4)
    tk.Button(actions_inner, text="📝 Add Comment (/comment)", bg=BORDER_COLOR, fg=TEXT_PRIMARY,
              command=lambda: process_command("/comment", "GUI"), **btn_style).pack(fill="x", pady=4)

    tk.Label(right_col,
             text="Operator Note:\nWO popup: 04:00–09:00\n/wo & /comment: 09:00–04:00",
             font=(FONT_FAMILY, 8), bg=PRIMARY_BG, fg=TEXT_MUTED, justify="left").pack(anchor="w", pady=(10, 0))

    # Startup sequence
    root.protocol("WM_DELETE_WINDOW", graceful_shutdown)
    update_gui_console("🚀 NRC-1 CCTV Master Console initializing...", "info")

    threading.Thread(target=master_loop, daemon=True).start()
    threading.Thread(target=telegram_poller, daemon=True).start()

    root.after(3000, check_input_queue)
    root.after(60000, auto_close_wo_prompts_at_9am)  # FIX: auto-close WO windows at 9 AM

    root.mainloop()
