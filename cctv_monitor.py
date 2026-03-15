import subprocess, platform, time, requests, sqlite3, os, smtplib, threading, sys, csv, shutil, configparser
import tkinter as tk
import tkinter.scrolledtext as st
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor

# ==============================================================================
# VISUAL THEME CONFIG (GUI ONLY) - Dark dashboard style
# ==============================================================================
PRIMARY_BG = "#0f172a"       # Main window background (dark slate)
CARD_BG = "#1e293b"          # Panels / cards (slightly lighter for contrast)
HEADER_BG = "#020617"        # Top header bar
HEADER_FG = "#e5e7eb"        # Header text
TEXT_PRIMARY = "#e5e7eb"     # Main text color
TEXT_MUTED = "#94a3b8"       # Muted/secondary text
ACCENT_BLUE = "#2563eb"      # Primary accent (buttons)
ACCENT_RED = "#ef4444"       # Danger accent
ACCENT_GREEN = "#22c55e"     # Success accent
ACCENT_ORANGE = "#ea580c"    # Primary action (like reference dashboard)
BORDER_COLOR = "#334155"     # Panel borders
FONT_FAMILY = "Segoe UI"     # Clean system font
CARD_PAD = 16                # Card inner padding

# ==============================================================================
# SECURITY CONFIGURATION
# ==============================================================================
config = configparser.ConfigParser()
if not os.path.exists('config.ini'):
    print("❌ ERROR: config.ini not found! Please create it with [SECRETS] section.")
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

# Global State Management
OFFLINE_QUEUE = []
LAST_TELE_ID = 0
RECOVERY_TRACKER = {}
ACTIVE_PROMPTS = {}
REPORT_SENT_DATE = None
GATEWAY_REACHABLE = True
WO_INPUT_PAUSE = False  # Pause monitoring when WO input is active

# GUI globals for current offline window
OFFLINE_WINDOW = None
OFFLINE_WINDOW_TEXT = None

# ==============================================================================
# DATABASE LAYER
# ==============================================================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Base table with incident_id and safe defaults
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
                    downtime_duration TEXT DEFAULT NULL,
                    maintenance_mode INTEGER DEFAULT 0,
                    incident_id TEXT DEFAULT NULL
                )''')

    # Auto-repair: add any missing columns if DB already exists
    required_columns = {
        'mail_eligible': 'INTEGER DEFAULT 0',
        'work_order': 'TEXT DEFAULT NULL',
        'comment': 'TEXT DEFAULT NULL',
        'down_time': 'TEXT DEFAULT NULL',
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

def get_mail_window_incidents():
    """All incidents from today's 4–9 AM window for /wo and /comment."""
    return query_db(
        """
        SELECT ip, name, location, down_time, work_order, comment
        FROM cameras
        WHERE down_time IS NOT NULL
          AND date(down_time) = date('now')
          AND CAST(strftime('%H', down_time) AS INTEGER) BETWEEN 4 AND 8
        ORDER BY down_time ASC
        """,
        ()
    )

def search_camera_gui():
    """Open search results window by name or IP."""
    try:
        val = search_entry.get().strip()
    except Exception:
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
    tk.Label(win, text=f"Search results for \"{val}\"", font=(FONT_FAMILY, 11, "bold"),
            bg=PRIMARY_BG, fg=TEXT_PRIMARY, anchor="w").pack(fill="x", padx=14, pady=(12, 4))
    txt = st.ScrolledText(win, bg=CARD_BG, fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
                          font=("Consolas", 10), relief="flat", borderwidth=1)
    txt.pack(fill="both", expand=True, padx=10, pady=(0, 12))
    if not res:
        txt.insert(tk.END, "❌ No matching assets found.")
    else:
        for r in res:
            stat = "🟢 ONLINE" if r[3] == 1 else "🔴 OFFLINE"
            maint = " [MUTED]" if r[6] == 1 else ""
            txt.insert(tk.END,
                f"[{stat}]{maint} {r[0]}\nIP: {r[1]} | Loc: {r[2]}\n"
                f"WO: {r[4] if r[4] else 'None'} | Down: {r[5]}\n{'-'*55}\n")
    txt.config(state="disabled")

def backup_database():
    try:
        if not os.path.exists("backups"):
            os.makedirs("backups")
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        shutil.copy2(DB_NAME, f"backups/backup_{ts}.db")
        update_gui_console("💾 DB Backup created successfully.", "info")
    except:
        pass

# ==============================================================================
# LOGGING, BACKLOG & SEARCH
# ==============================================================================
def check_for_backlog():
    global OFFLINE_QUEUE
    backlog = query_db(
        "SELECT ip FROM cameras "
        "WHERE mail_eligible = 1 AND (work_order IS NULL OR work_order = '') "
        "AND maintenance_mode = 0"
    )
    if backlog:
        backlog_ips = [item[0] for item in backlog]
        if backlog_ips not in OFFLINE_QUEUE:
            OFFLINE_QUEUE.append(backlog_ips)

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
                if datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S') > cutoff:
                    rows.append(row)
        with open(LOG_FILE, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(h)
            w.writerows(rows)
    except:
        pass

def log_to_csv(event_type, name, ip, location,
               duration="N/A", wo="N/A", comment="N/A",
               incident_id="N/A"):
    file_exists = os.path.isfile(LOG_FILE)
    try:
        with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "Timestamp",
                    "IncidentID",
                    "Event",
                    "Name",
                    "IP",
                    "Location",
                    "Downtime",
                    "WO",
                    "Comment"
                ])
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                incident_id,
                event_type,
                name,
                ip,
                location,
                duration,
                wo,
                comment
            ])
    except:
        pass

# ==============================================================================
# HIGH-SPEED MONITORING & EMAIL
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
            capture_output=True,
            text=True,
            timeout=2,
            startupinfo=si,
            creationflags=0x08000000 if is_win else 0
        )
        return "TTL=" in res.stdout
    except:
        return False

def _format_down_time(down_time_str):
    """Format DB down_time for report display (single line for email)."""
    if not down_time_str:
        return "—"
    try:
        dt = datetime.strptime(down_time_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d %b %Y, %H:%M")
    except Exception:
        return down_time_str

def send_daily_report():
    all_stats = query_db("SELECT status FROM cameras")
    if not all_stats:
        update_gui_console("⚠️ Report Aborted: No cameras found in database.", "error")
        return

    total_assets = len(all_stats)
    online_count = sum(1 for x in all_stats if x[0] == 1)
    offline_count = total_assets - online_count
    uptime_percentage = round((online_count / total_assets * 100), 1) if total_assets > 0 else 0

    incident_data = query_db(
        "SELECT name, location, status, work_order, comment, down_time, downtime_duration "
        "FROM cameras WHERE mail_eligible=1"
    )

    chart_url = (
        "https://quickchart.io/chart?"
        f"c={{type:'doughnut',data:{{labels:['Online','Offline'],"
        f"datasets:[{{data:[{online_count},{offline_count}],backgroundColor:['%2310b981','%23ef4444'],"
        "borderWidth:3,borderColor:'#fff'}}]}},options:{{responsive:true,plugins:{{legend:{{position:'bottom'}},"
        "datalabels:{{display:true,color:'#fff',font:{{weight:'bold',size:14}}}}}}}}}}"
    )

    if not incident_data:
        table_content = (
            "<tr><td colspan=\"7\" style=\"padding:28px 16px; text-align:center; color:#64748b; font-size:14px;\">"
            "No critical incidents or prolonged downtimes in this reporting window.</td></tr>"
        )
    else:
        table_content = ""
        for name, loc, status, wo, comment, down_time, duration in incident_data:
            status_color = "#10b981" if status == 1 else "#ef4444"
            status_text = "RECOVERED" if status == 1 else "OFFLINE"
            wo_display = (wo if wo and wo != "NOT_PROVIDED" else "—").replace("<", "&lt;").replace(">", "&gt;")
            comment_safe = (comment or "").replace("<", "&lt;").replace(">", "&gt;")[:80]
            if comment and len(comment or "") > 80:
                comment_safe += "…"
            offline_at = _format_down_time(down_time)
            duration_display = (duration if duration and status == 1 else "Ongoing").replace("<", "&lt;").replace(">", "&gt;")
            table_content += f"""
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 14px 12px; font-size: 13px; color: #334155;">{loc or '—'}</td>
                <td style="padding: 14px 12px; font-size: 13px; color: #0f172a; font-weight: 600;">{name or '—'}</td>
                <td style="padding: 14px 12px; font-size: 12px; color: #475569; white-space: nowrap;">{offline_at}</td>
                <td style="padding: 14px 12px; font-size: 12px; color: #475569;">{duration_display}</td>
                <td style="padding: 14px 12px; font-size: 12px; color: #475569;">{wo_display}</td>
                <td style="padding: 14px 12px; font-size: 11px; color: #64748b; max-width:140px;">{comment_safe or '—'}</td>
                <td style="padding: 14px 12px; text-align: center;">
                    <span style="background:{status_color}; color:#fff; padding:6px 14px; border-radius:20px; font-size:11px; font-weight:600;">{status_text}</span>
                </td>
            </tr>"""

    now_ts = datetime.now().strftime("%d %b %Y · %H:%M")
    report_date = datetime.now().strftime("%d %b %Y")
    gateway_status = "Healthy" if GATEWAY_REACHABLE else "Degraded"
    incident_count = len(incident_data) if incident_data else 0

    # Text fallback when chart image is blocked by email client
    chart_fallback = f"{online_count} Online · {offline_count} Offline"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>CCTV Operational Dashboard</title></head>
    <body style="margin:0; padding:0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f1f5f9;">
        <table width="100%" cellspacing="0" cellpadding="0" style="max-width: 640px; margin: 0 auto; padding: 28px 20px;">
            <tr><td>
                <div style="background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;">
                    <!-- Header -->
                    <div style="background: #0f172a; color: #fff; padding: 26px 24px; text-align: center;">
                        <h1 style="margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -0.02em;">CCTV Operational Dashboard</h1>
                        <p style="margin: 6px 0 0; font-size: 13px; color: #94a3b8;">{now_ts} · NRC-1</p>
                    </div>

                    <!-- Stats row -->
                    <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                        <tr>
                            <td width="33%" align="center" style="padding: 22px 12px; background: #fff; border-right: 1px solid #e2e8f0;">
                                <div style="font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: #64748b; margin-bottom: 6px;">Total Assets</div>
                                <div style="font-size: 30px; font-weight: 700; color: #0f172a;">{total_assets}</div>
                            </td>
                            <td width="33%" align="center" style="padding: 22px 12px; background: #f0fdf4; border-right: 1px solid #e2e8f0;">
                                <div style="font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: #059669; margin-bottom: 6px;">Online</div>
                                <div style="font-size: 30px; font-weight: 700; color: #047857;">{online_count}</div>
                            </td>
                            <td width="34%" align="center" style="padding: 22px 12px; background: #fef2f2;">
                                <div style="font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: #dc2626; margin-bottom: 6px;">Offline</div>
                                <div style="font-size: 30px; font-weight: 700; color: #b91c1c;">{offline_count}</div>
                            </td>
                        </tr>
                    </table>

                    <!-- Uptime + Chart -->
                    <div style="padding: 24px 24px 20px; text-align: center; background: #fafafa; border-bottom: 1px solid #e2e8f0;">
                        <div style="display: inline-block; background: #0f172a; color: #fff; padding: 14px 28px; border-radius: 10px; margin-bottom: 18px;">
                            <span style="font-size: 13px; color: #94a3b8;">Uptime</span>
                            <span style="font-size: 26px; font-weight: 700; margin-left: 10px;">{uptime_percentage}%</span>
                        </div>
                        <div style="min-height: 200px;">
                            <img src="{chart_url}" width="200" height="200" alt="Uptime chart" style="display: block; margin: 0 auto; border: 0;" />
                        </div>
                        <p style="margin: 10px 0 0; font-size: 12px; color: #64748b;">{chart_fallback}</p>
                    </div>

                    <!-- Incident summary -->
                    <div style="padding: 24px;">
                        <h2 style="margin: 0 0 6px; font-size: 17px; font-weight: 600; color: #0f172a;">Incident Summary</h2>
                        <p style="margin: 0 0 18px; font-size: 12px; color: #64748b;">Work orders, offline time and downtime for the reporting window. Report date: {report_date}.</p>
                        <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse; font-size: 12px; border: 1px solid #e2e8f0;">
                            <thead>
                                <tr style="background: #f8fafc;">
                                    <th style="padding: 12px 10px; text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; border-bottom: 1px solid #e2e8f0;">Location</th>
                                    <th style="padding: 12px 10px; text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; border-bottom: 1px solid #e2e8f0;">Asset</th>
                                    <th style="padding: 12px 10px; text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; border-bottom: 1px solid #e2e8f0;">Offline at</th>
                                    <th style="padding: 12px 10px; text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; border-bottom: 1px solid #e2e8f0;">Duration</th>
                                    <th style="padding: 12px 10px; text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; border-bottom: 1px solid #e2e8f0;">Work order</th>
                                    <th style="padding: 12px 10px; text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; border-bottom: 1px solid #e2e8f0;">Comment</th>
                                    <th style="padding: 12px 10px; text-align: center; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; border-bottom: 1px solid #e2e8f0;">Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {table_content}
                            </tbody>
                        </table>
                        <p style="margin: 14px 0 0; font-size: 11px; color: #94a3b8;">{incident_count} incident(s) in this report.</p>
                    </div>

                    <!-- Footer -->
                    <div style="background: #f8fafc; padding: 14px 24px; border-top: 1px solid #e2e8f0;">
                        <table width="100%" cellspacing="0" cellpadding="0"><tr>
                            <td style="font-size: 12px; color: #64748b;"><span style="color: #22c55e; font-weight: bold;">&#10003;</span> Automated diagnostic report &middot; Gateway: {GATEWAY_IP}</td>
                            <td align="right" style="font-size: 12px; color: #0f172a; font-weight: 600;">State: {gateway_status}</td>
                        </tr></table>
                    </div>
                </div>
            </td></tr>
        </table>
    </body>
    </html>
    """

    # 6. Dispatch via SMTP
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
        update_gui_console(f"✅ Dashboard sent (Total Assets: {total_assets})", "success")
    except Exception as e:
        error_msg = f"❌ Daily report email FAILED: {str(e)}"
        update_gui_console(error_msg, "error")
        try:
            send_telegram(
                f"🚨 <b>Daily Report Email FAILED</b>\n\n"
                f"<b>Error:</b> {str(e)}\n\n"
                f"Check SMTP/credentials and try again."
            )
        except Exception:
            pass  # GUI already shows the error

# ==============================================================================
# TELEGRAM COMMANDS & GUI UTILS
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

def broadcast_system_state(message: str):
    """
    Send a high-level system state message to both GUI and Telegram.
    Uses the 'action' tag in the console for emphasis.
    """
    update_gui_console(message, "action")
    send_telegram(message)

def update_gui_console(text, tag="info"):
    def _w():
        console_box.config(state='normal')

        if "Time:" in text:
            console_box.insert(tk.END, "» ", "time")
            console_box.insert(tk.END, f"{text}\n", tag)
        else:
            ts = datetime.now().strftime('%H:%M:%S')
            console_box.insert(tk.END, f"[{ts}] ", "time")
            console_box.insert(tk.END, f"{text}\n", tag)

        console_box.see(tk.END)
        console_box.config(state='disabled')

    root.after(0, _w)

def update_status_bar(total, online, offline, muted):
    root.after(
        0,
        lambda: [
            lbl_total.config(text=str(total)),
            lbl_online.config(text=str(online)),
            lbl_offline.config(text=str(offline)),
            lbl_muted.config(text=str(muted))
        ]
    )

def process_command(raw, src="GUI"):
    if not raw or not raw.strip():
        return
    p = raw.strip().split(" ", 1)
    b = p[0].lower()
    v = p[1] if len(p) > 1 else None

    if b == "/mute":
        if not v:
            msg = "Usage: /mute <ip>"
            update_gui_console(msg, "info")
            send_telegram(msg)
            return

        rows = query_db(
            "SELECT name, ip, location FROM cameras WHERE ip=?",
            (v,)
        )
        if not rows:
            msg = f"❌ Cannot mute: camera with IP {v} not found."
            update_gui_console(msg, "error")
            send_telegram(msg)
            return

        name, ip, loc = rows[0]
        query_db("UPDATE cameras SET maintenance_mode=1 WHERE ip=?", (ip,), commit=True)
        detail = f"🔇 Muted {name} (IP: {ip}, Loc: {loc})"
        update_gui_console(detail, "action")
        send_telegram(detail)

    elif b == "/unmute":
        if not v:
            msg = "Usage: /unmute <ip>"
            update_gui_console(msg, "info")
            send_telegram(msg)
            return

        rows = query_db(
            "SELECT name, ip, location FROM cameras WHERE ip=?",
            (v,)
        )
        if not rows:
            msg = f"❌ Cannot unmute: camera with IP {v} not found."
            update_gui_console(msg, "error")
            send_telegram(msg)
            return

        name, ip, loc = rows[0]
        query_db("UPDATE cameras SET maintenance_mode=0 WHERE ip=?", (ip,), commit=True)
        detail = f"🔊 Unmuted {name} (IP: {ip}, Loc: {loc})"
        update_gui_console(detail, "action")
        send_telegram(detail)

    elif b == "/wo":
        if v and ACTIVE_PROMPTS:
            ips = list(ACTIVE_PROMPTS.keys())[0].split(",")
            finalize_wo(ips, v, "TELEGRAM" if src == "TELEGRAM" else src)
        elif not v:
            if ACTIVE_PROMPTS:
                first_key = list(ACTIVE_PROMPTS.keys())[0]
                win = ACTIVE_PROMPTS[first_key]
                if win.winfo_exists():
                    win.lift()
                return
            rows = get_mail_window_incidents()
            pending = [r for r in rows if r[4] is None or r[4] == "" or r[4] == "NOT_PROVIDED"]
            if not pending:
                msg = "ℹ️ No 4–9 window cameras pending work order."
                update_gui_console(msg, "info")
                send_telegram(msg)
            else:
                ip, name, loc, down_time, _wo, _comment = pending[0]
                open_dual_input_window([ip])
        else:
            msg = "ℹ️ No active WO prompt. Use /wo (no number) to pick next 4–9 camera."
            update_gui_console(msg, "info")
            send_telegram(msg)

    elif b == "/comment":
        if not v:
            msg = "Usage: /comment <text>"
            update_gui_console(msg, "info")
            send_telegram(msg)
            return
        if ACTIVE_PROMPTS:
            ips = list(ACTIVE_PROMPTS.keys())[0].split(",")
            ph = ",".join(["?"] * len(ips))
            query_db(f"UPDATE cameras SET comment=? WHERE ip IN ({ph})", (v, *ips), commit=True)
            msg = f"📝 Comment saved via {src}: {v}"
            update_gui_console(msg, "success")
            send_telegram(msg)
        else:
            rows = get_mail_window_incidents()
            pending = [r for r in rows if r[5] is None or r[5] == ""]
            if not pending:
                msg = "ℹ️ No 4–9 window cameras pending comment."
                update_gui_console(msg, "info")
                send_telegram(msg)
            else:
                ip, name, loc, down_time, _wo, _comment = pending[0]
                query_db("UPDATE cameras SET comment=? WHERE ip=?", (v, ip), commit=True)
                msg = f"📝 Comment added to {name} (IP: {ip}, Loc: {loc}, Down: {down_time}): {v}"
                update_gui_console(msg, "success")
                send_telegram(msg)

    elif b == "/status":
        off = query_db(
            "SELECT COUNT(*) FROM cameras WHERE status=0 AND maintenance_mode=0"
        )[0][0]
        msg = f"📊 Critical Offline: {off}"
        update_gui_console(msg, "info")
        send_telegram(msg)
    
    else:
        # Invalid command handling
        valid_commands = ["/mute", "/unmute", "/wo", "/comment", "/status"]
        msg = f"❌ Invalid command: '{b}'\n\nValid commands:\n" + "\n".join(f"• {cmd}" for cmd in valid_commands)
        update_gui_console(msg, "error")
        send_telegram(msg)

# ==============================================================================
# STARTUP INCIDENT REPAIR
# ==============================================================================
def close_stale_open_incidents_on_startup():
    """
    Close incidents where the camera is currently ONLINE (status=1)
    but incident_id is still set – e.g. system rebooted during the 20‑minute
    stability window. This prevents 'stuck' open incidents after restart.
    """
    rows = query_db(
        "SELECT ip, name, location, down_time, work_order, comment, incident_id "
        "FROM cameras "
        "WHERE status=1 AND incident_id IS NOT NULL",
        ()
    )
    if not rows:
        return

    now = datetime.now()
    full_ts = now.strftime('%Y-%m-%d %H:%M:%S')

    for ip, name, loc, down_time, wo, comment, incident_id in rows:
        dur = "N/A"
        if down_time:
            try:
                dt = datetime.strptime(down_time, '%Y-%m-%d %H:%M:%S')
                dur = str(now - dt).split('.')[0]
            except Exception:
                pass

        # Log as RECOVERED using the same incident_id
        log_to_csv(
            "RECOVERED",
            name or ip,
            ip,
            loc or "N/A",
            duration=dur,
            wo=wo or "N/A",
            comment=comment or "N/A",
            incident_id=incident_id or "N/A"
        )

        # Clear incident flags and finalize downtime in DB
        query_db(
            "UPDATE cameras SET last_change=?, downtime_duration=?, "
            "mail_eligible=0, work_order=NULL, incident_id=NULL "
            "WHERE ip=?",
            (full_ts, dur, ip),
            commit=True
        )

        update_gui_console(
            f"♻️ Startup cleanup: closed stale incident for {name or ip} (IP: {ip}).",
            "info"
        )

# ==============================================================================
# CURRENT OFFLINE WINDOW (KEPT IN SYNC)
# ==============================================================================
def refresh_current_offline_window():
    global OFFLINE_WINDOW, OFFLINE_WINDOW_TEXT
    if OFFLINE_WINDOW is None or OFFLINE_WINDOW_TEXT is None:
        return
    if not OFFLINE_WINDOW.winfo_exists():
        OFFLINE_WINDOW = None
        OFFLINE_WINDOW_TEXT = None
        return

    res = query_db(
        "SELECT name, ip, location, work_order, down_time, maintenance_mode "
        "FROM cameras WHERE status=0 AND maintenance_mode=0"
    )

    OFFLINE_WINDOW_TEXT.config(state='normal')
    OFFLINE_WINDOW_TEXT.delete('1.0', tk.END)

    if not res:
        OFFLINE_WINDOW_TEXT.insert(tk.END, "✅ All critical cameras are online.\n")
    else:
        for name, ip, loc, wo, down_time, maint in res:
            OFFLINE_WINDOW_TEXT.insert(
                tk.END,
                f"[🔴 OFFLINE] {name}\n"
                f"IP: {ip} | Loc: {loc}\n"
                f"WO: {wo if wo else 'None'} | Down: {down_time or 'N/A'}\n"
                f"{'-'*45}\n"
            )

    OFFLINE_WINDOW_TEXT.config(state='disabled')

    root.after(5000, refresh_current_offline_window)

def show_current_offline():
    global OFFLINE_WINDOW, OFFLINE_WINDOW_TEXT

    if OFFLINE_WINDOW is not None and OFFLINE_WINDOW.winfo_exists():
        refresh_current_offline_window()
        OFFLINE_WINDOW.lift()
        return

    OFFLINE_WINDOW = tk.Toplevel(root)
    OFFLINE_WINDOW.title("Current Critical Offline Cameras")
    OFFLINE_WINDOW.configure(bg=PRIMARY_BG)
    OFFLINE_WINDOW.geometry("580x380")

    tk.Label(
        OFFLINE_WINDOW,
        text="Current Critical Offline Cameras",
        font=(FONT_FAMILY, 11, "bold"),
        bg=PRIMARY_BG,
        fg=TEXT_PRIMARY,
        anchor="w"
    ).pack(fill="x", padx=14, pady=(12, 4))

    OFFLINE_WINDOW_TEXT = st.ScrolledText(
        OFFLINE_WINDOW,
        bg=CARD_BG,
        fg=TEXT_PRIMARY,
        insertbackground=TEXT_PRIMARY,
        font=("Consolas", 10),
        relief='flat',
        borderwidth=1
    )
    OFFLINE_WINDOW_TEXT.pack(fill='both', expand=True, padx=10, pady=(0, 12))

    refresh_current_offline_window()

def graceful_shutdown():
    """
    Called when the GUI window is closed.
    Sends a friendly 'system stopping' notice to GUI and Telegram.
    """
    try:
        update_gui_console("🛑 NRC-1 CCTV Master Console stopping. Monitoring halted.", "action")
        send_telegram("🛑 <b>System STOPPED. Monitoring halted.</b>")
    except Exception:
        pass
    finally:
        root.destroy()

def run_monitor():
    global OFFLINE_QUEUE, RECOVERY_TRACKER, ACTIVE_PROMPTS, GATEWAY_REACHABLE, WO_INPUT_PAUSE

    # Monitoring always runs (ping, DB, CSV). GUI/Telegram alerts are gated below when WO window is open.

    # 1. Internet check (non-blocking for LAN monitoring)
    if not is_online("8.8.8.8"):
        update_gui_console("⚠️ No Internet connection detected. Continuing local LAN monitoring.", "error")

    # 2. Gateway check (can pause monitoring)
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

    # 3. Fetch Cameras & Run High-Speed Ping
    cams = query_db(
        "SELECT ip, name, status, down_time, mail_eligible, location, "
        "maintenance_mode, work_order, comment, incident_id "
        "FROM cameras"
    )
    if not cams:
        return

    with ThreadPoolExecutor(max_workers=200) as ex:
        results = list(ex.map(is_online, [c[0] for c in cams]))

    now = datetime.now()
    ts = now.strftime('%H:%M:%S')  # Time for display
    full_ts = now.strftime('%Y-%m-%d %H:%M:%S')  # Timestamp for DB
    mail_win = (4 <= now.hour < 9)
    cur_offline_grp = []
    on_cnt, off_cnt, muted_cnt = 0, 0, 0

    # 4. Process Results and Logic
    for i, (ip, name, old_stat, db_dt, is_el, loc,
            is_mut, wo, comment, incident_id) in enumerate(cams):
        new_stat = 1 if results[i] else 0

        if is_mut == 1:
            muted_cnt += 1

        # Count for status bar
        if new_stat == 1:
            on_cnt += 1
        elif is_mut == 0:
            off_cnt += 1

        # LOGIC: CAMERA WENT OFFLINE
        if new_stat == 0 and old_stat == 1:
            # Generate or reuse incident_id for this offline incident
            if not incident_id:
                incident_id = f"{ip}-{int(now.timestamp())}"

            detail_msg = (
                f"🔴 OFFLINE | Name: {name} | IP: {ip} | Time: {ts} | Loc: {loc} "
                f"| IncidentID: {incident_id}"
            )

            # Alerts only if NOT muted (per-IP; WO window no longer blocks alerts)
            if is_mut == 0:
                update_gui_console(detail_msg, "error")
                send_telegram(f"<b>{detail_msg}</b>")

            query_db(
                "UPDATE cameras SET status=0, last_change=?, down_time=?, incident_id=? WHERE ip=?",
                (full_ts, full_ts, incident_id, ip),
                commit=True
            )
            if ip in RECOVERY_TRACKER:
                del RECOVERY_TRACKER[ip]

            # Log OFFLINE event to CSV with incident_id (even if muted)
            log_to_csv(
                "OFFLINE",
                name,
                ip,
                loc,
                duration="N/A",
                wo=wo or "N/A",
                comment=comment or "N/A",
                incident_id=incident_id
            )

        # LOGIC: CAMERA RECOVERED
        if new_stat == 1 and old_stat == 0:
            if ip not in RECOVERY_TRACKER:
                detail_msg = f"🟢 RECOVERED | Name: {name} | IP: {ip} | Time: {ts} | Loc: {loc}"

                # Alerts only if NOT muted (per-IP)
                if is_mut == 0:
                    update_gui_console(detail_msg, "success")
                    send_telegram(f"<b>{detail_msg}</b>")

                query_db(
                    "UPDATE cameras SET status=1, last_change=? WHERE ip=?",
                    (full_ts, ip),
                    commit=True
                )
                RECOVERY_TRACKER[ip] = now  # Start stability timer

            elif (now - RECOVERY_TRACKER[ip]).total_seconds() / 60 >= 20:
                for k in list(ACTIVE_PROMPTS.keys()):
                    if ip in k.split(','):
                        w = ACTIVE_PROMPTS.pop(k)
                        root.after(0, w.destroy)

                dur = "N/A"
                if db_dt:
                    try:
                        dur = str(now - datetime.strptime(db_dt, '%Y-%m-%d %H:%M:%S')).split('.')[0]
                    except:
                        pass

                # Log RECOVERED event to CSV with same incident_id (even if muted)
                log_to_csv(
                    "RECOVERED",
                    name,
                    ip,
                    loc,
                    duration=dur,
                    wo=wo or "N/A",
                    comment=comment or "N/A",
                    incident_id=incident_id or "N/A"
                )

                query_db(
                    "UPDATE cameras SET last_change=?, downtime_duration=?, "
                    "mail_eligible=0, work_order=NULL, incident_id=NULL WHERE ip=?",
                    (full_ts, dur, ip),
                    commit=True
                )

                del RECOVERY_TRACKER[ip]

        # LOGIC: INCIDENT ELIGIBILITY (For 9AM Report)
        if new_stat == 0 and mail_win and not is_el and is_mut == 0:
            if db_dt and (now - datetime.strptime(db_dt, '%Y-%m-%d %H:%M:%S')).total_seconds() / 60 >= 20:
                query_db("UPDATE cameras SET mail_eligible=1 WHERE ip=?", (ip,), commit=True)
                cur_offline_grp.append(ip)

    # 5. Update UI Status Bar
    update_status_bar(len(cams), on_cnt, off_cnt, muted_cnt)

    # 6. Handle Work Order Prompts
    if cur_offline_grp:
        OFFLINE_QUEUE.append(cur_offline_grp)

def master_loop():
    global REPORT_SENT_DATE, WO_INPUT_PAUSE
    init_db()
    close_stale_open_incidents_on_startup()
    check_for_backlog()

    # Startup warm-up sequence (total ≈ 20 seconds)
    broadcast_system_state("🚦 NRC-1 CCTV Master Console starting. Warming up services...")
    time.sleep(10)

    broadcast_system_state("⚙️ System initializing core modules. Please wait...")
    time.sleep(10)

    # Final ONLINE announcement after warm-up
    update_gui_console("🚀 NRC-1 CCTV Master Console started", "success")
    send_telegram("🚀 <b>System ONLINE. Monitoring activated.</b>")

    while True:
        run_monitor()
        now = datetime.now()

        # 9 AM auto-close all WO prompts and resume monitoring
        if now.hour == 9 and now.minute == 0 and REPORT_SENT_DATE != now.date():
            # Force close all WO prompts
            for k in list(ACTIVE_PROMPTS.keys()):
                finalize_wo(k.split(","), "NOT_PROVIDED", "SYSTEM")
            
            # Resume monitoring
            WO_INPUT_PAUSE = False
            update_gui_console("✅ 9 AM auto-cleanup: Resuming normal monitoring", "success")

            send_daily_report()
            backup_database()
            cleanup_old_logs()

            REPORT_SENT_DATE = now.date()

        time.sleep(30)

def finalize_wo(ips, wo, src):
    global ACTIVE_PROMPTS, WO_INPUT_PAUSE
    ip_k = ",".join(ips)
    ph = ','.join(['?'] * len(ips))
    query_db(
        f"UPDATE cameras SET work_order=? WHERE ip IN ({ph})",
        (wo, *ips),
        commit=True
    )
    update_gui_console(f"✅ WO {wo} via {src}", "success")
    send_telegram(f"✅ WO {wo} assigned.")
    
    # Close the prompt window
    if ip_k in ACTIVE_PROMPTS:
        w = ACTIVE_PROMPTS.pop(ip_k)
        root.after(0, w.destroy)
    
    # Resume GUI/Telegram alerts if no more WO prompts open
    if not ACTIVE_PROMPTS:
        WO_INPUT_PAUSE = False
        update_gui_console("▶️ Alerts resumed - All WO inputs completed", "success")

def open_dual_input_window(ips):
    global ACTIVE_PROMPTS, WO_INPUT_PAUSE

    # Pause GUI/Telegram alerts until WO window is closed (monitoring continues in background)
    WO_INPUT_PAUSE = True
    update_gui_console("⏸️ Alerts paused - Enter WO below. Monitoring continues in background.", "action")

    placeholders = ",".join(["?"] * len(ips))
    rows = query_db(
        f"SELECT name, ip, location, down_time FROM cameras "
        f"WHERE ip IN ({placeholders})",
        ips
    )

    detail_lines = []
    for name, ip, loc, down_time in rows:
        down_str = "N/A"
        if down_time:
            try:
                down_dt = datetime.strptime(down_time, "%Y-%m-%d %H:%M:%S")
                down_str = down_dt.strftime("%H:%M")
            except Exception:
                down_str = down_time

        line = (
            f"{name} is OFFLINE | IP: {ip} | "
            f"Loc: {loc} | Down: {down_str}"
        )
        detail_lines.append(line)

    if not detail_lines:
        detail_lines = ["Selected camera(s) are offline."]

    full_text = "\n\n".join(detail_lines)

    tele_text = "⚠️ <b>WO REQUIRED</b>\n" + "\n".join(detail_lines)
    send_telegram(tele_text)

    prompt = tk.Toplevel(root)
    prompt.title("Work Order Required")
    prompt.configure(bg=PRIMARY_BG)

    # If user closes window with X (without submitting), resume alerts
    def _on_wo_window_close():
        global ACTIVE_PROMPTS, WO_INPUT_PAUSE
        if ip_k in ACTIVE_PROMPTS:
            ACTIVE_PROMPTS.pop(ip_k, None)
        if not ACTIVE_PROMPTS:
            WO_INPUT_PAUSE = False
            update_gui_console("▶️ WO window closed. Alerts resumed.", "info")
        try:
            prompt.destroy()
        except Exception:
            pass
    prompt.protocol("WM_DELETE_WINDOW", _on_wo_window_close)

    tk.Label(
        prompt,
        text="Pending Work Order",
        font=(FONT_FAMILY, 11, "bold"),
        bg=PRIMARY_BG,
        fg=TEXT_PRIMARY,
        anchor="w"
    ).pack(fill="x", padx=12, pady=(12, 4))

    tk.Label(
        prompt,
        text=full_text,
        wraplength=460,
        justify="left",
        anchor="w",
        fg=ACCENT_RED,
        bg=PRIMARY_BG,
        font=(FONT_FAMILY, 9)
    ).pack(padx=12, pady=(0, 8), fill="x")

    entry_frame = tk.Frame(prompt, bg=PRIMARY_BG)
    entry_frame.pack(fill="x", padx=12, pady=(0, 10))

    tk.Label(
        entry_frame,
        text="Work Order #",
        bg=PRIMARY_BG,
        fg=TEXT_MUTED,
        font=(FONT_FAMILY, 9)
    ).pack(anchor="w")

    wo_var = tk.StringVar()
    tk.Entry(
        entry_frame,
        textvariable=wo_var,
        font=(FONT_FAMILY, 10),
        bg=CARD_BG,
        fg=TEXT_PRIMARY,
        insertbackground=TEXT_PRIMARY,
        relief="flat"
    ).pack(fill="x", pady=(2, 0))

    tk.Button(
        prompt,
        text="Submit Work Order",
        command=lambda: finalize_wo(ips, wo_var.get().strip(), "GUI"),
        bg=ACCENT_BLUE,
        fg="white",
        activebackground="#1d4ed8",
        activeforeground="white",
        relief="flat",
        padx=10,
        pady=4
    ).pack(pady=(8, 12))

    ip_k = ",".join(ips)
    ACTIVE_PROMPTS[ip_k] = prompt

def check_input_queue():
    if OFFLINE_QUEUE and not WO_INPUT_PAUSE:  # Only process if not paused
        open_dual_input_window(OFFLINE_QUEUE.pop(0))
    root.after(3000, check_input_queue)

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

# ==============================================================================
# MAIN GUI SETUP (Dark dashboard – card layout, KPI row, quick actions)
# ==============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    root.title("NRC-1 CCTV MASTER CONSOLE V6.2")
    root.geometry("900x760")
    root.configure(bg=PRIMARY_BG)
    root.minsize(800, 600)

    # ----- Header -----
    header = tk.Frame(root, bg=HEADER_BG, height=56)
    header.pack(fill="x", side="top")
    header.pack_propagate(False)

    # Logo / title block
    title_f = tk.Frame(header, bg=HEADER_BG)
    title_f.pack(side="left", padx=20, pady=12)
    tk.Label(
        title_f, text="●", font=(FONT_FAMILY, 14), bg=HEADER_BG, fg=ACCENT_ORANGE
    ).pack(side="left", padx=(0, 8))
    tk.Label(
        title_f, text="NRC-1 CCTV", font=(FONT_FAMILY, 14, "bold"),
        bg=HEADER_BG, fg=HEADER_FG
    ).pack(side="left")
    tk.Label(
        title_f, text="  MASTER CONSOLE", font=(FONT_FAMILY, 10),
        bg=HEADER_BG, fg=TEXT_MUTED
    ).pack(side="left")

    tk.Label(
        header, text=f"Gateway: {GATEWAY_IP}", font=(FONT_FAMILY, 10),
        bg=HEADER_BG, fg=TEXT_MUTED
    ).pack(side="right", padx=20, pady=12)

    # ----- Content area -----
    content = tk.Frame(root, bg=PRIMARY_BG)
    content.pack(fill="both", expand=True, padx=20, pady=(16, 12))

    # Welcome line
    welcome_f = tk.Frame(content, bg=PRIMARY_BG)
    welcome_f.pack(fill="x", pady=(0, 16))
    tk.Label(
        welcome_f, text="CCTV Monitor", font=(FONT_FAMILY, 18, "bold"),
        bg=PRIMARY_BG, fg=HEADER_FG
    ).pack(anchor="w")
    tk.Label(
        welcome_f, text="Real-time camera status and alerts",
        font=(FONT_FAMILY, 11), bg=PRIMARY_BG, fg=TEXT_MUTED
    ).pack(anchor="w")

    # ----- Search row -----
    search_f = tk.Frame(content, bg=PRIMARY_BG)
    search_f.pack(fill="x", pady=(0, 12))
    tk.Label(search_f, text="Search Camera:", font=(FONT_FAMILY, 10), bg=PRIMARY_BG, fg=TEXT_MUTED).pack(side="left", padx=(0, 8))
    search_entry = tk.Entry(search_f, font=(FONT_FAMILY, 10), bg=CARD_BG, fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY, relief="flat")
    search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
    search_entry.bind("<Return>", lambda e: search_camera_gui())
    tk.Button(search_f, text="Find", command=search_camera_gui, bg=ACCENT_BLUE, fg="white", activebackground="#1d4ed8", activeforeground="white", relief="flat", padx=10, pady=3).pack(side="left")

    # ----- KPI cards row -----
    kpi_f = tk.Frame(content, bg=PRIMARY_BG)
    kpi_f.pack(fill="x", pady=(0, 16))

    def make_kpi_card(parent, label_text, value_var_placeholder, fg_icon="#94a3b8"):
        card = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER_COLOR, highlightthickness=1)
        card.pack(side="left", fill="x", expand=True, padx=(0, 10))
        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(fill="both", expand=True, padx=CARD_PAD, pady=CARD_PAD)
        tk.Label(inner, text=label_text, font=(FONT_FAMILY, 10), bg=CARD_BG, fg=TEXT_MUTED).pack(anchor="w")
        lbl = tk.Label(inner, text="-", font=(FONT_FAMILY, 26, "bold"), bg=CARD_BG, fg=fg_icon)
        lbl.pack(anchor="w")
        return lbl

    lbl_total = make_kpi_card(kpi_f, "Total Assets", None, TEXT_PRIMARY)
    lbl_online = make_kpi_card(kpi_f, "Online", None, ACCENT_GREEN)
    lbl_offline = make_kpi_card(kpi_f, "Critical Offline", None, ACCENT_RED)
    lbl_muted = make_kpi_card(kpi_f, "Muted", None, "#f97316")

    # ----- Two columns: Event Log (left) + Quick Actions (right) -----
    main_row = tk.Frame(content, bg=PRIMARY_BG)
    main_row.pack(fill="both", expand=True, pady=(0, 12))

    # Left: Event Log card
    log_card = tk.Frame(main_row, bg=CARD_BG, highlightbackground=BORDER_COLOR, highlightthickness=1)
    log_card.pack(side="left", fill="both", expand=True, padx=(0, 12))
    log_inner = tk.Frame(log_card, bg=CARD_BG)
    log_inner.pack(fill="both", expand=True, padx=12, pady=12)
    tk.Label(
        log_inner, text="Event Log", font=(FONT_FAMILY, 12, "bold"),
        bg=CARD_BG, fg=HEADER_FG
    ).pack(fill="x")
    console_box = st.ScrolledText(
        log_inner, width=50, height=20,
        bg="#0f172a", fg=TEXT_PRIMARY, font=("Consolas", 10),
        relief="flat", borderwidth=0, insertbackground=TEXT_PRIMARY
    )
    console_box.pack(fill="both", expand=True, pady=(8, 0))
    console_box.tag_config("error", foreground="#f87171")
    console_box.tag_config("success", foreground="#4ade80")
    console_box.tag_config("time", foreground="#94a3b8")
    console_box.tag_config("action", foreground="#fbbf24")
    console_box.config(state="disabled")

    # Right: Quick Actions
    right_col = tk.Frame(main_row, bg=PRIMARY_BG, width=240)
    right_col.pack(side="right", fill="y", padx=(0, 0))
    right_col.pack_propagate(False)

    tk.Label(
        right_col, text="Quick Actions", font=(FONT_FAMILY, 12, "bold"),
        bg=PRIMARY_BG, fg=HEADER_FG
    ).pack(anchor="w", pady=(0, 10))

    actions_card = tk.Frame(right_col, bg=CARD_BG, highlightbackground=BORDER_COLOR, highlightthickness=1)
    actions_card.pack(fill="x", pady=(0, 12))
    actions_inner = tk.Frame(actions_card, bg=CARD_BG)
    actions_inner.pack(fill="x", padx=12, pady=12)

    tk.Label(actions_inner, text="Command", font=(FONT_FAMILY, 10), bg=CARD_BG, fg=TEXT_MUTED).pack(anchor="w")
    cmd_entry = tk.Entry(
        actions_inner, font=(FONT_FAMILY, 11), bg=PRIMARY_BG, fg=TEXT_PRIMARY,
        insertbackground=TEXT_PRIMARY, relief="flat"
    )
    cmd_entry.pack(fill="x", pady=(4, 12))
    cmd_entry.bind("<Return>", lambda e: [process_command(cmd_entry.get()), cmd_entry.delete(0, tk.END)])

    tk.Button(
        actions_inner, text="  Current Offline  →", font=(FONT_FAMILY, 10),
        bg=ACCENT_ORANGE, fg="white", activebackground="#c2410c", activeforeground="white",
        relief="flat", cursor="hand2", command=show_current_offline
    ).pack(fill="x", pady=4)
    tk.Button(
        actions_inner, text="  /status  →", font=(FONT_FAMILY, 10),
        bg=CARD_BG, fg=TEXT_PRIMARY, activebackground=BORDER_COLOR, activeforeground=TEXT_PRIMARY,
        relief="flat", cursor="hand2", command=lambda: process_command("/status", "GUI")
    ).pack(fill="x", pady=4)
    tk.Button(
        actions_inner, text="  /wo  →", font=(FONT_FAMILY, 10),
        bg=CARD_BG, fg=TEXT_PRIMARY, activebackground=BORDER_COLOR, activeforeground=TEXT_PRIMARY,
        relief="flat", cursor="hand2", command=lambda: process_command("/wo", "GUI")
    ).pack(fill="x", pady=4)
    tk.Button(
        actions_inner, text="  /comment  →", font=(FONT_FAMILY, 10),
        bg=CARD_BG, fg=TEXT_PRIMARY, activebackground=BORDER_COLOR, activeforeground=TEXT_PRIMARY,
        relief="flat", cursor="hand2", command=lambda: process_command("/comment", "GUI")
    ).pack(fill="x", pady=4)

    # Footer hint
    tk.Label(
        right_col, text="Type full command in the field above\n(e.g. /status, /mute 192.168.1.1)",
        font=(FONT_FAMILY, 9), bg=PRIMARY_BG, fg=TEXT_MUTED, justify="left"
    ).pack(anchor="w", pady=(8, 0))

    # ----- Startup -----
    root.protocol("WM_DELETE_WINDOW", graceful_shutdown)
    update_gui_console("🚀 NRC-1 CCTV Master Console initializing…", "info")
    threading.Thread(target=master_loop, daemon=True).start()
    threading.Thread(target=telegram_poller, daemon=True).start()
    root.after(3000, check_input_queue)
    root.mainloop()
