import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, Listbox, Frame, Label, Button, Entry, filedialog, Toplevel, Text
import threading
import json
import requests
import os
import sys
import re
from datetime import datetime, timedelta
import math
import time
import urllib.parse
import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sqlite3

# ---- Helper to get base directory ----
def get_base_dir():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
import db

# ---- Optional imports ----
try:
    import caldav
    CALDAV_AVAILABLE = True
except ImportError:
    CALDAV_AVAILABLE = False

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ---- Optional dependencies ----
VOICE_AVAILABLE = False
TTS_AVAILABLE = False
SEARCH_AVAILABLE = False
PDF_AVAILABLE = False

try:
    import speech_recognition as sr
    VOICE_AVAILABLE = True
except ImportError:
    pass
try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    pass
try:
    from duckduckgo_search import DDGS
    SEARCH_AVAILABLE = True
except ImportError:
    try:
        from ddgs import DDGS
        SEARCH_AVAILABLE = True
    except ImportError:
        pass
try:
    from pypdf import PdfReader
    PDF_AVAILABLE = True
except ImportError:
    pass

# ---- Configuration ----
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
WORKSPACE_DIR = os.path.join(BASE_DIR, "gyani_workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

def load_config():
    default_config = {
        "llm_endpoint": "http://localhost:11434/api/chat",
        "model": "llama3.2:3b",
        "max_tokens": 2048,
        "temperature": 0.7,
        "system_prompt": (
            "You are Gyani Baba, a wise and helpful AI assistant with access to tools.\n"
            "When you need real-time information or capabilities, use these tools:\n"
            "  - Current date/time: output [DATETIME]\n"
            "  - Web search: output [SEARCH: query]\n"
            "  - Read file: output [READ: path]\n"
            "  - Write file: output [WRITE: path] followed by content on next line(s)\n"
            "  - Math calculation: output [CALCULATE: expression]\n"
            "  - Image generation: output [GENERATE: prompt] to create an image.\n"
            "  - Custom skills: output [SKILL: skill_name] to run a user-defined skill.\n"
            "Example: [GENERATE: a majestic mountain sunset with a wise old sage]\n"
            "Always use tools when needed. If you don't need a tool, just answer directly."
        ),
        "image_api_url": "https://image.pollinations.ai/prompt/",
        "image_width": 512,
        "image_height": 512,
        "email": {
            "smtp_server": "",
            "smtp_port": 587,
            "smtp_username": "",
            "smtp_password": "",
            "imap_server": "",
            "imap_port": 993,
            "imap_username": "",
            "imap_password": ""
        },
        "calendar": {
            "caldav_url": "",
            "username": "",
            "password": ""
        }
    }

    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_config, f, indent=2)
        return default_config

    if os.path.getsize(CONFIG_FILE) == 0:
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_config, f, indent=2)
        return default_config

    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        import shutil
        shutil.copy2(CONFIG_FILE, CONFIG_FILE + ".corrupt")
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_config, f, indent=2)
        return default_config

config = load_config()

# ============================================================
# Email Functions
# ============================================================
def send_email(to, subject, body):
    email_conf = config.get("email", {})
    smtp_server = email_conf.get("smtp_server")
    smtp_port = email_conf.get("smtp_port")
    username = email_conf.get("smtp_username")
    password = email_conf.get("smtp_password")
    if not all([smtp_server, smtp_port, username, password]):
        return "Error: SMTP settings incomplete. Please configure email in Settings."
    try:
        msg = MIMEMultipart()
        msg['From'] = username
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(username, password)
        server.send_message(msg)
        server.quit()
        return "Email sent successfully!"
    except Exception as e:
        return f"Error sending email: {str(e)}"

def fetch_inbox(limit=10):
    email_conf = config.get("email", {})
    imap_server = email_conf.get("imap_server")
    imap_port = email_conf.get("imap_port")
    username = email_conf.get("imap_username")
    password = email_conf.get("imap_password")
    if not all([imap_server, imap_port, username, password]):
        return "Error: IMAP settings incomplete."
    try:
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(username, password)
        mail.select('INBOX')
        status, data = mail.search(None, 'ALL')
        if status != 'OK':
            return "No emails found."
        email_ids = data[0].split()
        latest = email_ids[-limit:] if len(email_ids) > limit else email_ids
        emails = []
        for eid in reversed(latest):
            status, msg_data = mail.fetch(eid, '(RFC822)')
            if status != 'OK':
                continue
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            sender = msg.get('From', 'Unknown')
            subject = msg.get('Subject', '(No subject)')
            date = msg.get('Date', '')
            emails.append({'sender': sender, 'subject': subject, 'date': date})
        mail.close()
        mail.logout()
        return emails
    except Exception as e:
        return f"Error fetching inbox: {str(e)}"

# ============================================================
# Calendar Functions
# ============================================================
def get_calendar_client():
    cal_conf = config.get("calendar", {})
    url = cal_conf.get("caldav_url")
    username = cal_conf.get("username")
    password = cal_conf.get("password")
    if not all([url, username, password]):
        return None, "Calendar settings incomplete. Please configure in Settings."
    if not CALDAV_AVAILABLE:
        return None, "CalDAV library not installed. Run: pip install caldav"
    try:
        client = caldav.DAVClient(url=url, username=username, password=password)
        return client, None
    except Exception as e:
        return None, f"Connection error: {str(e)}"

def fetch_calendar_events(days=30):
    client, err = get_calendar_client()
    if err:
        return err
    try:
        principal = client.principal()
        calendars = principal.calendars()
        if not calendars:
            return "No calendars found."
        cal = calendars[0]
        now = datetime.now()
        end = now + timedelta(days=days)
        events = cal.date_search(now, end, expand=True)
        if not events:
            return []
        result = []
        for event in events:
            data = event.data
            import re
            summary_match = re.search(r'SUMMARY:(.+?)(?:\r?\n|$)', data)
            start_match = re.search(r'DTSTART(?:;TZID=[^:]+)?:([\dT]+)', data)
            end_match = re.search(r'DTEND(?:;TZID=[^:]+)?:([\dT]+)', data)
            if summary_match and start_match:
                summary = summary_match.group(1).strip()
                start_str = start_match.group(1).strip()
                try:
                    start_dt = datetime.strptime(start_str[:8], "%Y%m%d")
                    if 'T' in start_str:
                        start_dt = datetime.strptime(start_str, "%Y%m%dT%H%M%S")
                except:
                    start_dt = datetime.now()
                end_dt = None
                if end_match:
                    end_str = end_match.group(1).strip()
                    try:
                        end_dt = datetime.strptime(end_str[:8], "%Y%m%d")
                        if 'T' in end_str:
                            end_dt = datetime.strptime(end_str, "%Y%m%dT%H%M%S")
                    except:
                        pass
                result.append({
                    'summary': summary,
                    'start': start_dt,
                    'end': end_dt,
                    'data': data
                })
        return sorted(result, key=lambda x: x['start'])
    except Exception as e:
        return f"Error fetching calendar: {str(e)}"

def create_calendar_event(title, start_dt, end_dt, description=""):
    client, err = get_calendar_client()
    if err:
        return err
    try:
        principal = client.principal()
        calendars = principal.calendars()
        if not calendars:
            return "No calendars found."
        cal = calendars[0]
        vcal = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Gyani Baba//EN
BEGIN:VEVENT
UID:{int(time.time())}@gyani-baba
DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%S')}
DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}
DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}
SUMMARY:{title}
DESCRIPTION:{description}
END:VEVENT
END:VCALENDAR"""
        cal.save_event(vcal)
        return "Event created successfully!"
    except Exception as e:
        return f"Error creating event: {str(e)}"

# ============================================================
# Skills Management
# ============================================================
def get_all_skills():
    conn = db.get_connection()
    try:
        rows = conn.execute('SELECT * FROM skills ORDER BY name').fetchall()
        skills = []
        for row in rows:
            skills.append({
                'id': row['id'],
                'name': row['name'],
                'description': row['description'],
                'code': row['code']
            })
        return skills
    finally:
        conn.close()

def add_skill(name, description, code):
    conn = db.get_connection()
    try:
        conn.execute('INSERT INTO skills (name, description, code) VALUES (?, ?, ?)',
                     (name, description, code))
        conn.commit()
        return True, "Skill added!"
    except sqlite3.IntegrityError:
        return False, "Skill name already exists."
    finally:
        conn.close()

def update_skill(skill_id, name, description, code):
    conn = db.get_connection()
    try:
        conn.execute('UPDATE skills SET name = ?, description = ?, code = ? WHERE id = ?',
                     (name, description, code, skill_id))
        conn.commit()
        return True, "Skill updated!"
    except sqlite3.IntegrityError:
        return False, "Skill name already exists."
    finally:
        conn.close()

def delete_skill(skill_id):
    conn = db.get_connection()
    conn.execute('DELETE FROM skills WHERE id = ?', (skill_id,))
    conn.commit()
    conn.close()

def execute_skill_code(code, input_text):
    safe_globals = {
        '__builtins__': {
            'print': print,
            'len': len,
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
            'list': list,
            'dict': dict,
            'tuple': tuple,
            'range': range,
            'sum': sum,
            'min': min,
            'max': max,
            'abs': abs,
            'round': round,
            'input': None,
        },
        'input_text': input_text,
    }
    try:
        exec(code, safe_globals)
        result = safe_globals.get('result', None)
        if result is None:
            return "Skill executed, but no 'result' variable set."
        return str(result)
    except Exception as e:
        return f"Skill error: {str(e)}"

# ============================================================
# Tool functions
# ============================================================
def get_datetime():
    now = datetime.now()
    return now.strftime("%A, %B %d, %Y at %I:%M %p")

def calculate(expression):
    allowed = re.compile(r'^[\d+\-*/().\s]+$')
    if not allowed.match(expression):
        return "Error: Invalid expression"
    try:
        result = eval(expression, {"__builtins__": {}}, {"math": math})
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"

def search_web(query, max_results=3):
    if not SEARCH_AVAILABLE:
        return ["Search is not available."]
    try:
        with DDGS() as ddgs:
            results = []
            for r in ddgs.text(query, max_results=max_results):
                results.append(f"• {r['title']}\n  {r['body']}\n  Source: {r['href']}")
            return results or ["No results found."]
    except Exception as e:
        return [f"Search error: {str(e)}"]

def read_file(path):
    full_path = os.path.join(WORKSPACE_DIR, path)
    if not os.path.abspath(full_path).startswith(os.path.abspath(WORKSPACE_DIR)):
        return "Error: Access denied – path outside workspace."
    if not os.path.exists(full_path):
        return f"Error: File '{path}' not found."
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

def write_file(path, content):
    full_path = os.path.join(WORKSPACE_DIR, path)
    if not os.path.abspath(full_path).startswith(os.path.abspath(WORKSPACE_DIR)):
        return "Error: Access denied – path outside workspace."
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to '{path}'."
    except Exception as e:
        return f"Error writing file: {str(e)}"

def extract_text_from_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.txt':
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except:
            return None
    elif ext == '.pdf' and PDF_AVAILABLE:
        try:
            reader = PdfReader(file_path)
            text = ''
            for page in reader.pages:
                text += page.extract_text() + '\n'
            return text
        except:
            return None
    else:
        return None

def generate_image(prompt):
    api_url = config.get("image_api_url", "https://image.pollinations.ai/prompt/")
    width = config.get("image_width", 512)
    height = config.get("image_height", 512)
    if "pollinations" in api_url:
        base = api_url.rstrip('/')
        encoded = urllib.parse.quote(prompt)
        url = f"{base}/{encoded}?width={width}&height={height}"
    else:
        url = f"{api_url}?prompt={urllib.parse.quote(prompt)}&width={width}&height={height}"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        img_dir = os.path.join(WORKSPACE_DIR, "images")
        os.makedirs(img_dir, exist_ok=True)
        filename = f"gyani_{int(time.time())}.png"
        filepath = os.path.join(img_dir, filename)
        with open(filepath, "wb") as f:
            f.write(response.content)
        return filepath
    except Exception as e:
        return f"Error: {str(e)}"

# ============================================================
# LLM Client (with Skill detection)
# ============================================================
class GyaniLLM:
    def __init__(self):
        self.endpoint = config["llm_endpoint"]
        self.model = config["model"]
        self.max_tokens = config["max_tokens"]
        self.temperature = config["temperature"]
        self.system_prompt = config["system_prompt"]
        self.history = []

    def set_history(self, history):
        self.history = history

    def add_message(self, role, content):
        self.history.append({"role": role, "content": content})

    def clear_history(self):
        self.history = []

    def _call_llm(self, messages, callback):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens
            }
        }
        full_response = ""
        try:
            response = requests.post(self.endpoint, json=payload, stream=True, timeout=120)
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line.decode("utf-8"))
                        if "message" in chunk and "content" in chunk["message"]:
                            content = chunk["message"]["content"]
                            full_response += content
                            callback(content)
                    except json.JSONDecodeError:
                        continue
            return full_response
        except requests.exceptions.RequestException as e:
            callback(f"Error: {str(e)}")
            callback(None)
            return None

    def send_message(self, user_message, callback, on_image=None):
        self.add_message("user", user_message)
        messages = [
            {"role": "system", "content": self.system_prompt},
            *self.history
        ]
        max_iter = 3
        iteration = 0
        final_answer = ""

        while iteration < max_iter:
            iteration += 1
            full_response = self._call_llm(messages, callback)
            if full_response is None:
                break

            # Tool detection
            if re.search(r'\[DATETIME\]', full_response, re.IGNORECASE):
                callback("\n[Getting current date/time...]\n")
                now = get_datetime()
                messages.append({"role": "user", "content": f"Current date/time: {now}"})
                continue

            calc_match = re.search(r'\[CALCULATE:\s*(.+?)\]', full_response, re.IGNORECASE)
            if calc_match:
                expr = calc_match.group(1).strip()
                callback(f"\n[Calculating: {expr}...]\n")
                result = calculate(expr)
                messages.append({"role": "user", "content": f"Calculation result: {result}"})
                continue

            search_match = re.search(r'\[SEARCH:\s*(.+?)\]', full_response, re.IGNORECASE)
            if search_match:
                query = search_match.group(1).strip()
                callback(f"\n[Searching for '{query}'...]\n")
                results = search_web(query)
                context = "Search results:\n" + "\n".join(results)
                messages.append({"role": "user", "content": f"Search results: {context}"})
                continue

            read_match = re.search(r'\[READ:\s*(.+?)\]', full_response, re.IGNORECASE)
            if read_match:
                path = read_match.group(1).strip()
                callback(f"\n[Reading file: '{path}'...]\n")
                content = read_file(path)
                messages.append({"role": "user", "content": f"File content:\n{content}"})
                continue

            write_match = re.search(r'\[WRITE:\s*(.+?)\](?:\n|\s)(.*?)(?=\[|$)', full_response, re.DOTALL | re.IGNORECASE)
            if write_match:
                path = write_match.group(1).strip()
                content = write_match.group(2).strip()
                callback(f"\n[Writing to file: '{path}'...]\n")
                result = write_file(path, content)
                messages.append({"role": "user", "content": f"Write result: {result}"})
                continue

            # Image generation
            generate_match = re.search(r'\[GENERATE:\s*(.+?)\]', full_response, re.IGNORECASE)
            if generate_match:
                prompt = generate_match.group(1).strip()
                callback(f"\n[Generating image: '{prompt}'...]\n")
                filepath = generate_image(prompt)
                if filepath.startswith("Error"):
                    messages.append({"role": "user", "content": f"Image generation failed: {filepath}"})
                else:
                    if on_image:
                        on_image(filepath)
                    messages.append({"role": "user", "content": f"Image generated and saved to {filepath}"})
                continue

            # Skill execution
            skill_match = re.search(r'\[SKILL:\s*(.+?)\]', full_response, re.IGNORECASE)
            if skill_match:
                skill_name = skill_match.group(1).strip()
                callback(f"\n[Executing skill: '{skill_name}'...]\n")
                conn = db.get_connection()
                try:
                    row = conn.execute('SELECT code FROM skills WHERE name = ?', (skill_name,)).fetchone()
                    if not row:
                        result = f"Error: Skill '{skill_name}' not found."
                    else:
                        code = row[0]
                        result = execute_skill_code(code, "")
                except Exception as e:
                    result = f"Error: {str(e)}"
                finally:
                    conn.close()
                messages.append({"role": "user", "content": f"Skill result: {result}"})
                continue

            # No tool – final answer
            final_answer = full_response
            self.add_message("assistant", final_answer)
            break

        if not final_answer and full_response:
            final_answer = full_response or "I'm sorry, I couldn't process that."
        callback(None)
        return final_answer

# ============================================================
# Professional GUI
# ============================================================
class GyaniApp:
    def __init__(self, root):
        self.root = root
        root.title("Gyani Baba – Wise AI Assistant")
        root.geometry("1200x750")
        root.minsize(1000, 650)
        root.configure(bg="#0e0e1a")

        # ---- Load icon ----
        icon_path = os.path.join(BASE_DIR, "myicon.ico")
        if os.path.exists(icon_path):
            try:
                root.iconbitmap(icon_path)
            except:
                pass

        # ---- Menu Bar ----
        menubar = tk.Menu(root, bg="#1a1a2e", fg="#e5e7eb", activebackground="#2d2d44", activeforeground="#fbbf24")

        tools_menu = tk.Menu(menubar, tearoff=0, bg="#1a1a2e", fg="#e5e7eb")
        tools_menu.add_command(label="⚙️ Manage Skills", command=self.open_skill_manager)
        tools_menu.add_separator()
        tools_menu.add_command(label="📅 Calendar", command=self.open_calendar)
        tools_menu.add_command(label="📬 Inbox", command=self.open_inbox)
        tools_menu.add_command(label="✉️ Compose Email", command=self.open_compose_email)
        menubar.add_cascade(label="🛠️ Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg="#1a1a2e", fg="#e5e7eb")
        help_menu.add_command(label="ℹ️ About", command=self.show_about)
        menubar.add_cascade(label="❓ Help", menu=help_menu)

        root.config(menu=menubar)

        # ---- Data ----
        self.llm = GyaniLLM()
        self.sessions = db.load_sessions()
        self.current_session = None
        self.last_response = ""
        self.attachments = []
        self.processing = False

        # ---- Main Container ----
        main_container = tk.Frame(root, bg="#0e0e1a")
        main_container.pack(fill=tk.BOTH, expand=True)

        # ---- Sidebar ----
        sidebar = tk.Frame(main_container, bg="#14142a", width=240)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        header_frame = tk.Frame(sidebar, bg="#1f1f3a", height=80)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        logo_label = tk.Label(header_frame, text="🧘 Gyani Baba",
                              font=("Segoe UI", 20, "bold"),
                              fg="#fbbf24", bg="#1f1f3a")
        logo_label.pack(pady=20)

        new_btn = tk.Button(sidebar, text="✚ New Chat",
                           command=self.new_session,
                           font=("Segoe UI", 10, "bold"),
                           bg="#d97706", fg="white",
                           relief=tk.FLAT, padx=15, pady=10,
                           activebackground="#b45309",
                           activeforeground="white",
                           cursor="hand2",
                           highlightthickness=0,
                           bd=0)
        new_btn.pack(pady=(10, 10), padx=15, fill=tk.X)

        list_frame = tk.Frame(sidebar, bg="#14142a")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.session_list = Listbox(list_frame,
                                    bg="#14142a",
                                    fg="#c4b5d4",
                                    selectbackground="#2d2d44",
                                    selectforeground="#ffffff",
                                    font=("Segoe UI", 10),
                                    relief=tk.FLAT,
                                    highlightthickness=0,
                                    borderwidth=0,
                                    activestyle="none")
        self.session_list.pack(fill=tk.BOTH, expand=True)
        self.session_list.bind("<<ListboxSelect>>", self.on_session_select)

        del_btn = tk.Button(sidebar, text="🗑 Delete Chat",
                           command=self.delete_session,
                           font=("Segoe UI", 9),
                           bg="#2d2d44", fg="#ef4444",
                           relief=tk.FLAT, padx=10, pady=6,
                           activebackground="#3d3d55",
                           activeforeground="#f87171",
                           cursor="hand2",
                           highlightthickness=0,
                           bd=0)
        del_btn.pack(pady=(5, 15), padx=15, fill=tk.X)

        # ---- Main Content ----
        content = tk.Frame(main_container, bg="#0e0e1a")
        content.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # ---- Gradient Header ----
        header = tk.Frame(content, bg="#1a1a2e", height=70)
        header.pack(fill=tk.X, side=tk.TOP)
        canvas = tk.Canvas(header, height=70, bg="#1a1a2e", highlightthickness=0)
        canvas.pack(fill=tk.X)
        for i in range(70):
            r = int(20 + i*0.2)
            g = int(20 + i*0.2)
            b = int(40 + i*0.3)
            color = f"#{r:02x}{g:02x}{b:02x}"
            canvas.create_rectangle(0, i, 2000, i+1, fill=color, outline="")

        title_label = tk.Label(header, text="Gyani Baba", font=("Segoe UI", 18, "bold"),
                               fg="#fbbf24", bg="#1a1a2e")
        title_label.place(x=20, y=20)

        version_label = tk.Label(header, text="v1.0.1", font=("Segoe UI", 9),
                                 fg="#6b7280", bg="#1a1a2e")
        version_label.place(x=200, y=28)

        creator_label = tk.Label(header, text="by Vinod Prajapati", font=("Segoe UI", 8),
                                 fg="#6b7280", bg="#1a1a2e")
        creator_label.place(x=200, y=45)

        model_label = tk.Label(header, text=f"Model: {config['model']}",
                               font=("Segoe UI", 9), fg="#6b7280", bg="#1a1a2e")
        model_label.place(x=260, y=28)

        # ---- Chat Area ----
        chat_container = tk.Frame(content, bg="#0e0e1a")
        chat_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=(5, 0))

        chat_frame = tk.Frame(chat_container, bg="#0e0e1a")
        chat_frame.pack(fill=tk.BOTH, expand=True)

        self.chat = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            font=("Segoe UI", 11),
            bg="#0e0e1a",
            fg="#e5e7eb",
            insertbackground="#fbbf24",
            relief=tk.FLAT,
            highlightthickness=0,
            padx=20,
            pady=10,
            spacing2=2
        )
        self.chat.pack(fill=tk.BOTH, expand=True)

        # ---- Tags ----
        self.chat.tag_config("user_name", foreground="#fbbf24", font=("Segoe UI", 10, "bold"))
        self.chat.tag_config("user_bubble",
                            background="#2d2d44",
                            foreground="#e5e7eb",
                            lmargin1=80, lmargin2=80,
                            rmargin=20,
                            wrap=tk.WORD,
                            spacing2=5,
                            spacing3=8)
        self.chat.tag_config("assistant_name", foreground="#34d399", font=("Segoe UI", 10, "bold"))
        self.chat.tag_config("assistant_bubble",
                            background="#1a1a2e",
                            foreground="#e5e7eb",
                            lmargin1=20, lmargin2=20,
                            rmargin=80,
                            wrap=tk.WORD,
                            spacing2=5,
                            spacing3=8)
        self.chat.tag_config("system_bubble",
                            foreground="#6b7280",
                            font=("Segoe UI", 9, "italic"),
                            justify="center",
                            spacing2=10,
                            spacing3=10)
        self.chat.tag_config("timestamp", foreground="#4b5563", font=("Segoe UI", 8))
        self.chat.tag_config("attachment", foreground="#fbbf24", font=("Segoe UI", 9, "bold"))
        self.chat.tag_config("bold", font=("Segoe UI", 11, "bold"))
        self.chat.tag_config("italic", font=("Segoe UI", 11, "italic"))
        self.chat.tag_config("code", font=("Consolas", 10), background="#1a1a2e", foreground="#fcd34d")
        self.chat.tag_config("bullet", lmargin1=40, lmargin2=60)

        # ---- Typing Indicator ----
        self.typing_frame = tk.Frame(chat_container, bg="#0e0e1a", height=30)
        self.typing_frame.pack(fill=tk.X, pady=(0, 5))
        self.typing_label = tk.Label(self.typing_frame, text="Gyani Baba is thinking...",
                                     font=("Segoe UI", 10, "italic"),
                                     fg="#fbbf24", bg="#0e0e1a")
        self.typing_label.pack(side=tk.LEFT, padx=20)
        self.typing_frame.pack_forget()

        # ---- Input Area ----
        input_container = tk.Frame(content, bg="#0e0e1a", height=90)
        input_container.pack(fill=tk.X, side=tk.BOTTOM, padx=15, pady=(0, 15))

        self.attach_frame = tk.Frame(input_container, bg="#0e0e1a", height=30)
        self.attach_frame.pack(fill=tk.X, pady=(0, 5))
        self.attach_frame.pack_forget()

        input_frame = tk.Frame(input_container, bg="#1a1a2e", highlightthickness=0, bd=0)
        input_frame.pack(fill=tk.X, ipadx=5, ipady=5)

        self.entry = Entry(
            input_frame,
            font=("Segoe UI", 11),
            bg="#1a1a2e",
            fg="#e5e7eb",
            insertbackground="#fbbf24",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightcolor="#2d2d44",
            highlightbackground="#2d2d44"
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(15, 5), pady=8)
        self.entry.bind("<Return>", lambda e: self.send())

        # ---- Buttons ----
        btn_style = {"font": ("Segoe UI", 12), "bg": "#1a1a2e", "fg": "#fbbf24",
                     "relief": tk.FLAT, "padx": 8, "pady": 5,
                     "activebackground": "#2d2d44", "activeforeground": "#fcd34d",
                     "cursor": "hand2", "highlightthickness": 0, "bd": 0}

        self.attach_btn = Button(input_frame, text="📎", command=self.attach_file, **btn_style)
        self.attach_btn.pack(side=tk.RIGHT, padx=2)

        self.image_btn = Button(input_frame, text="🎨", command=self.open_image_dialog, **btn_style)
        self.image_btn.pack(side=tk.RIGHT, padx=2)

        self.email_btn = Button(input_frame, text="✉️", command=self.open_compose_email, **btn_style)
        self.email_btn.pack(side=tk.RIGHT, padx=2)

        if VOICE_AVAILABLE:
            self.listen_btn = Button(input_frame, text="🎤", command=self.listen_voice, **btn_style)
            self.listen_btn.pack(side=tk.RIGHT, padx=2)

        self.send_btn = Button(
            input_frame,
            text="→",
            command=self.send,
            font=("Segoe UI", 14),
            bg="#d97706",
            fg="white",
            relief=tk.FLAT,
            padx=15,
            pady=5,
            activebackground="#b45309",
            activeforeground="white",
            cursor="hand2",
            highlightthickness=0,
            bd=0
        )
        self.send_btn.pack(side=tk.RIGHT, padx=(0, 10))

        # ---- Status Bar ----
        status_frame = tk.Frame(content, bg="#1a1a2e", height=28)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.status = tk.Label(status_frame, text="Ready", fg="#6b7280", bg="#1a1a2e",
                               font=("Segoe UI", 9))
        self.status.pack(side=tk.LEFT, padx=15)

        btn_status_style = {"font": ("Segoe UI", 9), "bg": "#2d2d44", "fg": "#fbbf24",
                            "relief": tk.FLAT, "padx": 10, "pady": 2,
                            "activebackground": "#3d3d55", "activeforeground": "#fcd34d",
                            "cursor": "hand2", "highlightthickness": 0, "bd": 0}
        self.inbox_btn = Button(status_frame, text="📬 Inbox", command=self.open_inbox, **btn_status_style)
        self.inbox_btn.pack(side=tk.LEFT, padx=5)

        self.calendar_btn = Button(status_frame, text="📅 Calendar", command=self.open_calendar, **btn_status_style)
        self.calendar_btn.pack(side=tk.LEFT, padx=5)

        self.settings_btn = Button(status_frame, text="⚙️ Settings", command=self.open_settings, **btn_status_style)
        self.settings_btn.pack(side=tk.LEFT, padx=5)

        ws_label = tk.Label(status_frame, text=f"📁 {WORKSPACE_DIR}", fg="#4b5563",
                            bg="#1a1a2e", font=("Segoe UI", 8))
        ws_label.pack(side=tk.RIGHT, padx=15)

        # ---- TTS ----
        self.tts = None
        if TTS_AVAILABLE:
            try:
                self.tts = pyttsx3.init()
                self.tts.setProperty('rate', 150)
                self.tts.setProperty('volume', 0.9)
            except:
                self.tts = None

        # ---- Load existing sessions ----
        if self.sessions:
            self.current_session = 0
            self.refresh_sidebar()
            self.load_session(0)
        else:
            self.new_session()

    # ============================================================
    # About Dialog
    # ============================================================
    def show_about(self):
        about = Toplevel(self.root)
        about.title("About Gyani Baba")
        about.geometry("400x300")
        about.configure(bg="#1a1a2e")
        about.resizable(False, False)

        tk.Label(about, text="🧘", font=("Segoe UI", 48), bg="#1a1a2e").pack(pady=(20,0))
        tk.Label(about, text="Gyani Baba", font=("Segoe UI", 18, "bold"),
                 fg="#fbbf24", bg="#1a1a2e").pack(pady=(5,0))
        tk.Label(about, text="Version 1.0.1", font=("Segoe UI", 10),
                 fg="#6b7280", bg="#1a1a2e").pack()
        tk.Label(about, text="Created by Vinod Prajapati", font=("Segoe UI", 10),
                 fg="#d1d4e0", bg="#1a1a2e").pack(pady=(5,0))
        tk.Label(about, text="A wise AI assistant with tools, skills,\nemail, calendar, and image generation.",
                 font=("Segoe UI", 9), fg="#6b7280", bg="#1a1a2e", justify="center").pack(pady=10)
        tk.Button(about, text="Close", command=about.destroy,
                  bg="#d97706", fg="white", font=("Segoe UI", 10), relief=tk.FLAT, padx=20).pack(pady=15)

    # ============================================================
    # Settings
    # ============================================================
    def open_settings(self):
        win = Toplevel(self.root)
        win.title("Settings")
        win.geometry("550x600")
        win.configure(bg="#1a1a2e")
        win.resizable(False, False)

        tk.Label(win, text="📧 Email Settings", font=("Segoe UI", 12, "bold"),
                 fg="#fbbf24", bg="#1a1a2e").grid(row=0, column=0, columnspan=2, pady=(10,5), sticky="w", padx=20)

        tk.Label(win, text="SMTP Server:", fg="#e5e7eb", bg="#1a1a2e").grid(row=1, column=0, sticky="e", padx=10, pady=2)
        smtp_server = tk.Entry(win, width=30, bg="#2d2d44", fg="white")
        smtp_server.grid(row=1, column=1, padx=10, pady=2, sticky="w")
        smtp_server.insert(0, config.get("email", {}).get("smtp_server", ""))

        tk.Label(win, text="SMTP Port:", fg="#e5e7eb", bg="#1a1a2e").grid(row=2, column=0, sticky="e", padx=10, pady=2)
        smtp_port = tk.Entry(win, width=30, bg="#2d2d44", fg="white")
        smtp_port.grid(row=2, column=1, padx=10, pady=2, sticky="w")
        smtp_port.insert(0, str(config.get("email", {}).get("smtp_port", 587)))

        tk.Label(win, text="SMTP Username:", fg="#e5e7eb", bg="#1a1a2e").grid(row=3, column=0, sticky="e", padx=10, pady=2)
        smtp_user = tk.Entry(win, width=30, bg="#2d2d44", fg="white")
        smtp_user.grid(row=3, column=1, padx=10, pady=2, sticky="w")
        smtp_user.insert(0, config.get("email", {}).get("smtp_username", ""))

        tk.Label(win, text="SMTP Password:", fg="#e5e7eb", bg="#1a1a2e").grid(row=4, column=0, sticky="e", padx=10, pady=2)
        smtp_pass = tk.Entry(win, width=30, bg="#2d2d44", fg="white", show="*")
        smtp_pass.grid(row=4, column=1, padx=10, pady=2, sticky="w")
        smtp_pass.insert(0, config.get("email", {}).get("smtp_password", ""))

        tk.Label(win, text="IMAP Server:", fg="#e5e7eb", bg="#1a1a2e").grid(row=5, column=0, sticky="e", padx=10, pady=2)
        imap_server = tk.Entry(win, width=30, bg="#2d2d44", fg="white")
        imap_server.grid(row=5, column=1, padx=10, pady=2, sticky="w")
        imap_server.insert(0, config.get("email", {}).get("imap_server", ""))

        tk.Label(win, text="IMAP Port:", fg="#e5e7eb", bg="#1a1a2e").grid(row=6, column=0, sticky="e", padx=10, pady=2)
        imap_port = tk.Entry(win, width=30, bg="#2d2d44", fg="white")
        imap_port.grid(row=6, column=1, padx=10, pady=2, sticky="w")
        imap_port.insert(0, str(config.get("email", {}).get("imap_port", 993)))

        tk.Label(win, text="IMAP Username:", fg="#e5e7eb", bg="#1a1a2e").grid(row=7, column=0, sticky="e", padx=10, pady=2)
        imap_user = tk.Entry(win, width=30, bg="#2d2d44", fg="white")
        imap_user.grid(row=7, column=1, padx=10, pady=2, sticky="w")
        imap_user.insert(0, config.get("email", {}).get("imap_username", ""))

        tk.Label(win, text="IMAP Password:", fg="#e5e7eb", bg="#1a1a2e").grid(row=8, column=0, sticky="e", padx=10, pady=2)
        imap_pass = tk.Entry(win, width=30, bg="#2d2d44", fg="white", show="*")
        imap_pass.grid(row=8, column=1, padx=10, pady=2, sticky="w")
        imap_pass.insert(0, config.get("email", {}).get("imap_password", ""))

        tk.Label(win, text="📅 Calendar Settings", font=("Segoe UI", 12, "bold"),
                 fg="#fbbf24", bg="#1a1a2e").grid(row=9, column=0, columnspan=2, pady=(15,5), sticky="w", padx=20)

        tk.Label(win, text="CalDAV URL:", fg="#e5e7eb", bg="#1a1a2e").grid(row=10, column=0, sticky="e", padx=10, pady=2)
        cal_url = tk.Entry(win, width=30, bg="#2d2d44", fg="white")
        cal_url.grid(row=10, column=1, padx=10, pady=2, sticky="w")
        cal_url.insert(0, config.get("calendar", {}).get("caldav_url", ""))

        tk.Label(win, text="CalDAV Username:", fg="#e5e7eb", bg="#1a1a2e").grid(row=11, column=0, sticky="e", padx=10, pady=2)
        cal_user = tk.Entry(win, width=30, bg="#2d2d44", fg="white")
        cal_user.grid(row=11, column=1, padx=10, pady=2, sticky="w")
        cal_user.insert(0, config.get("calendar", {}).get("username", ""))

        tk.Label(win, text="CalDAV Password:", fg="#e5e7eb", bg="#1a1a2e").grid(row=12, column=0, sticky="e", padx=10, pady=2)
        cal_pass = tk.Entry(win, width=30, bg="#2d2d44", fg="white", show="*")
        cal_pass.grid(row=12, column=1, padx=10, pady=2, sticky="w")
        cal_pass.insert(0, config.get("calendar", {}).get("password", ""))

        def save_settings():
            config["email"] = {
                "smtp_server": smtp_server.get().strip(),
                "smtp_port": int(smtp_port.get().strip() or 587),
                "smtp_username": smtp_user.get().strip(),
                "smtp_password": smtp_pass.get().strip(),
                "imap_server": imap_server.get().strip(),
                "imap_port": int(imap_port.get().strip() or 993),
                "imap_username": imap_user.get().strip(),
                "imap_password": imap_pass.get().strip()
            }
            config["calendar"] = {
                "caldav_url": cal_url.get().strip(),
                "username": cal_user.get().strip(),
                "password": cal_pass.get().strip()
            }
            with open(CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)
            messagebox.showinfo("Success", "Settings saved!")
            win.destroy()

        btn_frame = tk.Frame(win, bg="#1a1a2e")
        btn_frame.grid(row=13, column=0, columnspan=2, pady=20)
        tk.Button(btn_frame, text="Save", command=save_settings,
                  bg="#d97706", fg="white", font=("Segoe UI", 10), relief=tk.FLAT, padx=20).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=win.destroy,
                  bg="#2d2d44", fg="white", font=("Segoe UI", 10), relief=tk.FLAT, padx=20).pack(side=tk.LEFT, padx=10)

    # ============================================================
    # Compose Email
    # ============================================================
    def open_compose_email(self):
        win = Toplevel(self.root)
        win.title("Compose Email")
        win.geometry("500x400")
        win.configure(bg="#1a1a2e")
        win.resizable(False, False)

        tk.Label(win, text="To:", fg="#e5e7eb", bg="#1a1a2e").grid(row=0, column=0, sticky="e", padx=10, pady=5)
        to_entry = tk.Entry(win, width=40, bg="#2d2d44", fg="white")
        to_entry.grid(row=0, column=1, padx=10, pady=5, sticky="w")

        tk.Label(win, text="Subject:", fg="#e5e7eb", bg="#1a1a2e").grid(row=1, column=0, sticky="e", padx=10, pady=5)
        sub_entry = tk.Entry(win, width=40, bg="#2d2d44", fg="white")
        sub_entry.grid(row=1, column=1, padx=10, pady=5, sticky="w")

        tk.Label(win, text="Body:", fg="#e5e7eb", bg="#1a1a2e").grid(row=2, column=0, sticky="ne", padx=10, pady=5)
        body_text = Text(win, width=40, height=10, bg="#2d2d44", fg="white", wrap=tk.WORD)
        body_text.grid(row=2, column=1, padx=10, pady=5, sticky="w")

        def send_email_action():
            to = to_entry.get().strip()
            subject = sub_entry.get().strip()
            body = body_text.get("1.0", tk.END).strip()
            if not all([to, subject, body]):
                messagebox.showwarning("Incomplete", "Please fill all fields.")
                return
            result = send_email(to, subject, body)
            messagebox.showinfo("Email Status", result)
            win.destroy()

        btn_frame = tk.Frame(win, bg="#1a1a2e")
        btn_frame.grid(row=3, column=0, columnspan=2, pady=15)
        tk.Button(btn_frame, text="Send", command=send_email_action,
                  bg="#d97706", fg="white", font=("Segoe UI", 10), relief=tk.FLAT, padx=20).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=win.destroy,
                  bg="#2d2d44", fg="white", font=("Segoe UI", 10), relief=tk.FLAT, padx=20).pack(side=tk.LEFT, padx=10)

    # ============================================================
    # Inbox
    # ============================================================
    def open_inbox(self):
        win = Toplevel(self.root)
        win.title("Inbox")
        win.geometry("700x450")
        win.configure(bg="#1a1a2e")
        win.resizable(False, False)

        tk.Label(win, text="Recent Emails", font=("Segoe UI", 14, "bold"),
                 fg="#fbbf24", bg="#1a1a2e").pack(pady=10)

        listbox = Listbox(win, bg="#2d2d44", fg="#e5e7eb", font=("Segoe UI", 10),
                          relief=tk.FLAT, highlightthickness=0)
        listbox.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        def fetch_thread():
            self.status.config(text="Fetching inbox...")
            result = fetch_inbox(limit=15)
            if isinstance(result, str):
                win.after(0, lambda: listbox.insert(tk.END, result))
                win.after(0, lambda: self.status.config(text="Ready"))
                return
            for email_item in result:
                display = f"{email_item['date']} | {email_item['sender']} | {email_item['subject']}"
                win.after(0, lambda d=display: listbox.insert(tk.END, d))
            win.after(0, lambda: self.status.config(text="Inbox loaded"))

        threading.Thread(target=fetch_thread, daemon=True).start()

    # ============================================================
    # Calendar
    # ============================================================
    def open_calendar(self):
        win = Toplevel(self.root)
        win.title("Calendar")
        win.geometry("750x500")
        win.configure(bg="#1a1a2e")
        win.resizable(True, True)

        tk.Label(win, text="📅 Upcoming Events", font=("Segoe UI", 14, "bold"),
                 fg="#fbbf24", bg="#1a1a2e").pack(pady=10)

        toolbar = tk.Frame(win, bg="#1a1a2e")
        toolbar.pack(fill=tk.X, padx=20, pady=5)

        tk.Button(toolbar, text="➕ Add Event", command=lambda: self.add_event_dialog(win),
                  bg="#d97706", fg="white", font=("Segoe UI", 9), relief=tk.FLAT, padx=10).pack(side=tk.LEFT, padx=5)
        tk.Button(toolbar, text="🔄 Sync", command=lambda: self.refresh_calendar(win, event_list),
                  bg="#2d2d44", fg="#fbbf24", font=("Segoe UI", 9), relief=tk.FLAT, padx=10).pack(side=tk.LEFT, padx=5)

        tk.Label(toolbar, text="(next 30 days)", fg="#6b7280", bg="#1a1a2e",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=10)

        event_list = Listbox(win, bg="#2d2d44", fg="#e5e7eb", font=("Segoe UI", 10),
                             relief=tk.FLAT, highlightthickness=0, selectmode=tk.SINGLE)
        event_list.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        status_label = tk.Label(win, text="Loading events...", fg="#6b7280", bg="#1a1a2e",
                                font=("Segoe UI", 9))
        status_label.pack(pady=5)

        def fetch_thread():
            status_label.config(text="Fetching events...")
            if not CALDAV_AVAILABLE:
                event_list.insert(tk.END, "CalDAV library not installed. Run: pip install caldav")
                status_label.config(text="Error")
                return
            result = fetch_calendar_events(days=30)
            if isinstance(result, str):
                event_list.insert(tk.END, result)
                status_label.config(text="Error")
                return
            if not result:
                event_list.insert(tk.END, "No upcoming events found.")
                status_label.config(text="No events")
                return
            for event in result:
                start_str = event['start'].strftime("%Y-%m-%d %H:%M") if event['start'] else "Unknown"
                display = f"{start_str} | {event['summary']}"
                event_list.insert(tk.END, display)
            status_label.config(text=f"{len(result)} events loaded")

        threading.Thread(target=fetch_thread, daemon=True).start()

    def refresh_calendar(self, parent_win, listbox):
        listbox.delete(0, tk.END)
        listbox.insert(tk.END, "Refreshing...")

        def fetch_thread():
            if not CALDAV_AVAILABLE:
                listbox.delete(0, tk.END)
                listbox.insert(tk.END, "CalDAV library not installed. Run: pip install caldav")
                return
            result = fetch_calendar_events(days=30)
            listbox.delete(0, tk.END)
            if isinstance(result, str):
                listbox.insert(tk.END, result)
                return
            if not result:
                listbox.insert(tk.END, "No upcoming events found.")
                return
            for event in result:
                start_str = event['start'].strftime("%Y-%m-%d %H:%M") if event['start'] else "Unknown"
                display = f"{start_str} | {event['summary']}"
                listbox.insert(tk.END, display)

        threading.Thread(target=fetch_thread, daemon=True).start()

    def add_event_dialog(self, parent):
        dialog = Toplevel(parent)
        dialog.title("Add Event")
        dialog.geometry("450x300")
        dialog.configure(bg="#1a1a2e")
        dialog.resizable(False, False)

        tk.Label(dialog, text="Add New Event", font=("Segoe UI", 14, "bold"),
                 fg="#fbbf24", bg="#1a1a2e").pack(pady=10)

        tk.Label(dialog, text="Title:", fg="#e5e7eb", bg="#1a1a2e").pack(anchor="w", padx=20, pady=2)
        title_entry = tk.Entry(dialog, width=40, bg="#2d2d44", fg="white")
        title_entry.pack(padx=20, pady=2, fill=tk.X)

        dt_frame = tk.Frame(dialog, bg="#1a1a2e")
        dt_frame.pack(fill=tk.X, padx=20, pady=5)

        tk.Label(dt_frame, text="Date:", fg="#e5e7eb", bg="#1a1a2e").pack(side=tk.LEFT, padx=5)
        date_entry = tk.Entry(dt_frame, width=12, bg="#2d2d44", fg="white")
        date_entry.pack(side=tk.LEFT, padx=5)
        date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))

        tk.Label(dt_frame, text="Time:", fg="#e5e7eb", bg="#1a1a2e").pack(side=tk.LEFT, padx=10)
        time_entry = tk.Entry(dt_frame, width=8, bg="#2d2d44", fg="white")
        time_entry.pack(side=tk.LEFT, padx=5)
        time_entry.insert(0, datetime.now().strftime("%H:%M"))

        tk.Label(dt_frame, text="Duration (min):", fg="#e5e7eb", bg="#1a1a2e").pack(side=tk.LEFT, padx=10)
        dur_entry = tk.Entry(dt_frame, width=5, bg="#2d2d44", fg="white")
        dur_entry.pack(side=tk.LEFT, padx=5)
        dur_entry.insert(0, "60")

        tk.Label(dialog, text="Description:", fg="#e5e7eb", bg="#1a1a2e").pack(anchor="w", padx=20, pady=2)
        desc_text = Text(dialog, width=40, height=4, bg="#2d2d44", fg="white", wrap=tk.WORD)
        desc_text.pack(padx=20, pady=2, fill=tk.X)

        def create_event():
            title = title_entry.get().strip()
            date_str = date_entry.get().strip()
            time_str = time_entry.get().strip()
            duration = int(dur_entry.get().strip() or 60)
            desc = desc_text.get("1.0", tk.END).strip()
            if not title:
                messagebox.showwarning("Incomplete", "Please enter a title.")
                return
            try:
                start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                end_dt = start_dt + timedelta(minutes=duration)
            except:
                messagebox.showerror("Error", "Invalid date/time format. Use YYYY-MM-DD and HH:MM")
                return

            if not CALDAV_AVAILABLE:
                messagebox.showerror("Error", "CalDAV library not installed.")
                return

            result = create_calendar_event(title, start_dt, end_dt, desc)
            messagebox.showinfo("Event Status", result)
            if "Error" not in result:
                dialog.destroy()
                self.refresh_calendar(parent, parent.winfo_children()[1])

        btn_frame = tk.Frame(dialog, bg="#1a1a2e")
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="Create", command=create_event,
                  bg="#d97706", fg="white", font=("Segoe UI", 10), relief=tk.FLAT, padx=20).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy,
                  bg="#2d2d44", fg="white", font=("Segoe UI", 10), relief=tk.FLAT, padx=20).pack(side=tk.LEFT, padx=10)

    # ============================================================
    # Skills Manager
    # ============================================================
    def open_skill_manager(self):
        win = Toplevel(self.root)
        win.title("Skills Manager")
        win.geometry("700x500")
        win.configure(bg="#1a1a2e")
        win.resizable(True, True)

        tk.Label(win, text="🧠 Custom Skills", font=("Segoe UI", 14, "bold"),
                 fg="#fbbf24", bg="#1a1a2e").pack(pady=10)

        listbox = Listbox(win, bg="#2d2d44", fg="#e5e7eb", font=("Segoe UI", 10),
                          relief=tk.FLAT, highlightthickness=0)
        listbox.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        btn_frame = tk.Frame(win, bg="#1a1a2e")
        btn_frame.pack(fill=tk.X, padx=20, pady=5)

        def refresh_list():
            listbox.delete(0, tk.END)
            skills = get_all_skills()
            for skill in skills:
                listbox.insert(tk.END, f"{skill['name']} – {skill['description']}")

        def add_skill():
            self.edit_skill_dialog(win, refresh_list, mode="add")

        def edit_skill():
            sel = listbox.curselection()
            if not sel:
                messagebox.showinfo("Info", "Please select a skill to edit.")
                return
            idx = sel[0]
            skills = get_all_skills()
            if idx >= len(skills):
                return
            skill = skills[idx]
            self.edit_skill_dialog(win, refresh_list, mode="edit", skill=skill)

        def delete_skill():
            sel = listbox.curselection()
            if not sel:
                messagebox.showinfo("Info", "Please select a skill to delete.")
                return
            idx = sel[0]
            skills = get_all_skills()
            if idx >= len(skills):
                return
            skill = skills[idx]
            if messagebox.askyesno("Confirm", f"Delete skill '{skill['name']}'?"):
                delete_skill(skill['id'])
                refresh_list()

        tk.Button(btn_frame, text="➕ Add", command=add_skill,
                  bg="#d97706", fg="white", font=("Segoe UI", 9), relief=tk.FLAT, padx=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="✏️ Edit", command=edit_skill,
                  bg="#2d2d44", fg="#fbbf24", font=("Segoe UI", 9), relief=tk.FLAT, padx=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🗑 Delete", command=delete_skill,
                  bg="#2d2d44", fg="#ef4444", font=("Segoe UI", 9), relief=tk.FLAT, padx=10).pack(side=tk.LEFT, padx=5)

        refresh_list()

    def edit_skill_dialog(self, parent, refresh_callback, mode="add", skill=None):
        dialog = Toplevel(parent)
        dialog.title("Add Skill" if mode == "add" else "Edit Skill")
        dialog.geometry("500x450")
        dialog.configure(bg="#1a1a2e")
        dialog.resizable(False, False)

        tk.Label(dialog, text="Skill Name:", fg="#e5e7eb", bg="#1a1a2e").pack(anchor="w", padx=20, pady=2)
        name_entry = tk.Entry(dialog, width=50, bg="#2d2d44", fg="white")
        name_entry.pack(padx=20, pady=2, fill=tk.X)
        if skill:
            name_entry.insert(0, skill['name'])

        tk.Label(dialog, text="Description (what it does):", fg="#e5e7eb", bg="#1a1a2e").pack(anchor="w", padx=20, pady=2)
        desc_entry = tk.Entry(dialog, width=50, bg="#2d2d44", fg="white")
        desc_entry.pack(padx=20, pady=2, fill=tk.X)
        if skill:
            desc_entry.insert(0, skill['description'])

        tk.Label(dialog, text="Python Code (must set 'result' variable):", fg="#e5e7eb", bg="#1a1a2e").pack(anchor="w", padx=20, pady=2)
        code_text = Text(dialog, width=50, height=10, bg="#2d2d44", fg="white", wrap=tk.WORD, font=("Consolas", 10))
        code_text.pack(padx=20, pady=2, fill=tk.BOTH, expand=True)
        if skill:
            code_text.insert("1.0", skill['code'])
        else:
            code_text.insert("1.0", "# Example: get weather from wttr.in\nimport requests\nresponse = requests.get('https://wttr.in/London?format=%C+%t')\nresult = response.text")

        def save():
            name = name_entry.get().strip()
            desc = desc_entry.get().strip()
            code = code_text.get("1.0", tk.END).strip()
            if not name or not code:
                messagebox.showwarning("Incomplete", "Name and code are required.")
                return
            if mode == "add":
                ok, msg = add_skill(name, desc, code)
            else:
                ok, msg = update_skill(skill['id'], name, desc, code)
            if ok:
                messagebox.showinfo("Success", msg)
                dialog.destroy()
                refresh_callback()
            else:
                messagebox.showerror("Error", msg)

        btn_frame = tk.Frame(dialog, bg="#1a1a2e")
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Save", command=save,
                  bg="#d97706", fg="white", font=("Segoe UI", 10), relief=tk.FLAT, padx=20).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy,
                  bg="#2d2d44", fg="white", font=("Segoe UI", 10), relief=tk.FLAT, padx=20).pack(side=tk.LEFT, padx=10)

    # ============================================================
    # Markdown and Display helpers
    # ============================================================
    def render_markdown(self, text):
        lines = text.splitlines()
        for line in lines:
            if not line.strip():
                self.chat.insert(tk.END, "\n")
                continue
            if re.match(r'^[\s]*[-*]\s+', line):
                content = re.sub(r'^[\s]*[-*]\s+', '', line)
                self.chat.insert(tk.END, "  • ", "bullet")
                self._insert_formatted(content)
                self.chat.insert(tk.END, "\n")
                continue
            if re.match(r'^[\s]*\d+\.\s+', line):
                content = re.sub(r'^[\s]*\d+\.\s+', '', line)
                self.chat.insert(tk.END, "  1. ", "bullet")
                self._insert_formatted(content)
                self.chat.insert(tk.END, "\n")
                continue
            self._insert_formatted(line)
            self.chat.insert(tk.END, "\n")

    def _insert_formatted(self, text):
        i = 0
        while i < len(text):
            if text[i] == '`':
                end = text.find('`', i+1)
                if end != -1:
                    code = text[i+1:end]
                    self.chat.insert(tk.END, code, "code")
                    i = end + 1
                    continue
            if text[i:i+2] == '**':
                end = text.find('**', i+2)
                if end != -1:
                    bold = text[i+2:end]
                    self.chat.insert(tk.END, bold, "bold")
                    i = end + 2
                    continue
            if text[i] == '*' and (i+1 < len(text) and text[i+1] != '*'):
                end = text.find('*', i+1)
                if end != -1:
                    italic = text[i+1:end]
                    self.chat.insert(tk.END, italic, "italic")
                    i = end + 1
                    continue
            self.chat.insert(tk.END, text[i])
            i += 1

    # ============================================================
    # Session Management
    # ============================================================
    def new_session(self):
        name = f"Chat {len(self.sessions)+1}"
        session = {
            "id": None,
            "name": name,
            "messages": [],
            "history": []
        }
        session["id"] = db.save_session(session)
        self.sessions.append(session)
        self.current_session = len(self.sessions) - 1
        self.refresh_sidebar()
        self.load_session(self.current_session)

    def delete_session(self):
        if len(self.sessions) <= 1:
            messagebox.showinfo("Info", "Cannot delete the last session.")
            return
        idx = self.current_session
        session_id = self.sessions[idx]['id']
        db.delete_session(session_id)
        del self.sessions[idx]
        self.current_session = min(idx, len(self.sessions)-1)
        self.refresh_sidebar()
        self.load_session(self.current_session)

    def on_session_select(self, event):
        if not self.session_list.curselection():
            return
        idx = self.session_list.curselection()[0]
        if idx != self.current_session:
            self.current_session = idx
            self.load_session(idx)

    def refresh_sidebar(self):
        self.session_list.delete(0, tk.END)
        for sess in self.sessions:
            self.session_list.insert(tk.END, sess["name"])
        if self.current_session is not None:
            self.session_list.selection_set(self.current_session)
            self.session_list.activate(self.current_session)

    def load_session(self, idx):
        session = self.sessions[idx]
        self.chat.config(state="normal")
        self.chat.delete(1.0, tk.END)
        self.chat.config(state="disabled")
        self.llm.set_history(session["history"])
        for msg in session["messages"]:
            self.display_message(msg["sender"], msg["text"], store=False)
        self.status.config(text=f"Session: {session['name']}")

    # ============================================================
    # File Attachment
    # ============================================================
    def attach_file(self):
        file_paths = filedialog.askopenfilenames(
            title="Attach File(s)",
            filetypes=[
                ("All files", "*.*"),
                ("Text files", "*.txt"),
                ("PDF files", "*.pdf"),
                ("Python files", "*.py"),
                ("Markdown files", "*.md"),
                ("Images", "*.png *.jpg *.jpeg *.gif *.bmp")
            ]
        )
        if not file_paths:
            return
        for path in file_paths:
            self.attachments.append(path)
        self.update_attachment_preview()

    def update_attachment_preview(self):
        for widget in self.attach_frame.winfo_children():
            widget.destroy()
        if not self.attachments:
            self.attach_frame.pack_forget()
            return
        self.attach_frame.pack(fill=tk.X, pady=(0, 5))
        for path in self.attachments:
            fname = os.path.basename(path)
            label = tk.Label(self.attach_frame, text=f"📎 {fname}",
                             bg="#2d2d44", fg="#fbbf24",
                             font=("Segoe UI", 9),
                             padx=8, pady=2, relief=tk.FLAT)
            label.pack(side=tk.LEFT, padx=3)
            remove_btn = tk.Button(self.attach_frame, text="✕",
                                   command=lambda p=path: self.remove_attachment(p),
                                   bg="#2d2d44", fg="#ef4444",
                                   font=("Segoe UI", 8), relief=tk.FLAT,
                                   padx=3, pady=0, cursor="hand2")
            remove_btn.pack(side=tk.LEFT, padx=0)

    def remove_attachment(self, file_path):
        if file_path in self.attachments:
            self.attachments.remove(file_path)
        self.update_attachment_preview()

    # ============================================================
    # Image Generation (UI button)
    # ============================================================
    def open_image_dialog(self):
        dialog = Toplevel(self.root)
        dialog.title("Generate Image")
        dialog.geometry("400x180")
        dialog.configure(bg="#1a1a2e")

        tk.Label(dialog, text="Enter image description:", font=("Segoe UI", 11),
                 fg="#e5e7eb", bg="#1a1a2e").pack(pady=(15,5))

        entry = tk.Entry(dialog, font=("Segoe UI", 11), bg="#2d2d44", fg="white",
                         relief=tk.FLAT, highlightthickness=1)
        entry.pack(fill=tk.X, padx=20, pady=10)
        entry.focus_set()
        entry.bind("<Return>", lambda e: self._do_generate(entry.get(), dialog))

        btn_frame = tk.Frame(dialog, bg="#1a1a2e")
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Generate", command=lambda: self._do_generate(entry.get(), dialog),
                  bg="#d97706", fg="white", font=("Segoe UI", 10), relief=tk.FLAT, padx=20).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy,
                  bg="#2d2d44", fg="white", font=("Segoe UI", 10), relief=tk.FLAT, padx=20).pack(side=tk.LEFT, padx=5)

    def _do_generate(self, prompt, dialog):
        if not prompt.strip():
            messagebox.showwarning("Warning", "Please enter a prompt.")
            return
        dialog.destroy()
        self.status.config(text="Generating image...")
        self.root.update()

        def generate_thread():
            filepath = generate_image(prompt)
            if filepath.startswith("Error"):
                self.root.after(0, lambda: messagebox.showerror("Error", filepath))
                self.root.after(0, lambda: self.status.config(text="Ready"))
                return
            self.root.after(0, lambda: self.show_image_preview(filepath))
            self.root.after(0, lambda: self.status.config(text="Image generated"))
            self.display_message("assistant", f"I generated an image for: '{prompt}'", store=True)
        threading.Thread(target=generate_thread, daemon=True).start()

    def show_image_preview(self, image_path):
        if not os.path.exists(image_path):
            messagebox.showerror("Error", "Image file not found.")
            return
        if not PIL_AVAILABLE:
            os.startfile(image_path)
            return

        win = Toplevel(self.root)
        win.title("Generated Image")
        win.geometry("600x600")
        win.configure(bg="#0a0a12")

        img = Image.open(image_path)
        img.thumbnail((550, 550), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)

        label = tk.Label(win, image=photo, bg="#0a0a12")
        label.image = photo
        label.pack(pady=20)

        btn = tk.Button(win, text="Close", command=win.destroy,
                        font=("Segoe UI", 10), bg="#d97706", fg="white",
                        relief=tk.FLAT, padx=15, pady=5)
        btn.pack(pady=10)

        timestamp = datetime.now().strftime("%I:%M %p")
        self.chat.config(state="normal")
        self.chat.insert(tk.END, f"  🖼️ Gyani Baba generated an image  {timestamp}\n", "system_bubble")
        self.chat.insert(tk.END, f"  [Image saved: {os.path.basename(image_path)}]\n\n", "system_bubble")
        self.chat.see(tk.END)
        self.chat.config(state="disabled")
        if self.current_session is not None:
            session = self.sessions[self.current_session]
            session["messages"].append({"sender": "system", "text": f"Generated image: {os.path.basename(image_path)}"})
            db.save_session(session)

    # ============================================================
    # Display Message
    # ============================================================
    def display_message(self, sender, text, store=True, attachments=None):
        if store and self.current_session is not None:
            session = self.sessions[self.current_session]
            session["messages"].append({"sender": sender, "text": text})
            db.save_session(session)

        self.chat.config(state="normal")
        timestamp = datetime.now().strftime("%I:%M %p")
        if attachments:
            attach_str = " ".join([f"📎 {os.path.basename(p)}" for p in attachments])
            text = f"{text}\n\n{attach_str}"

        if sender == "user":
            self.chat.insert(tk.END, f"  👤 You  ", "user_name")
            self.chat.insert(tk.END, f"    {timestamp}\n", "timestamp")
            self.chat.insert(tk.END, f"{text}\n\n", "user_bubble")
        elif sender == "assistant":
            self.chat.insert(tk.END, f"  🧘 Gyani Baba  ", "assistant_name")
            self.chat.insert(tk.END, f"   {timestamp}\n", "timestamp")
            self.render_markdown(text)
            self.chat.insert(tk.END, "\n\n")
        else:
            self.chat.insert(tk.END, f"  ⚙️ {text}\n\n", "system_bubble")

        self.chat.see(tk.END)
        self.chat.config(state="disabled")

    def show_typing(self):
        self.typing_frame.pack(fill=tk.X, pady=(0, 5))
        self.typing_label.config(text="Gyani Baba is thinking...")
        self.root.update()

    def hide_typing(self):
        self.typing_frame.pack_forget()
        self.root.update()

    # ============================================================
    # Send Message
    # ============================================================
    def send(self):
        if self.processing:
            return
        msg = self.entry.get().strip()
        if not msg and not self.attachments:
            return

        image_match = re.search(r'(?:create|generate|make|draw|paint)\s+(?:an?\s+)?image\s+(?:of\s+)?(.+)', msg, re.IGNORECASE)
        if image_match:
            prompt = image_match.group(1).strip()
            if not prompt:
                prompt = msg
            self.entry.delete(0, tk.END)
            self.send_btn.config(state="disabled")
            if hasattr(self, 'listen_btn'):
                self.listen_btn.config(state="disabled")
            self.processing = True
            self.status.config(text="Generating image...")
            self.display_message("user", msg)
            def gen_thread():
                filepath = generate_image(prompt)
                if filepath.startswith("Error"):
                    self.root.after(0, lambda: messagebox.showerror("Error", filepath))
                    self.root.after(0, lambda: self.status.config(text="Ready"))
                    self.root.after(0, lambda: setattr(self, 'processing', False))
                    self.root.after(0, lambda: self.send_btn.config(state="normal"))
                    if hasattr(self, 'listen_btn'):
                        self.root.after(0, lambda: self.listen_btn.config(state="normal"))
                    return
                self.root.after(0, lambda: self.show_image_preview(filepath))
                self.root.after(0, lambda: self.status.config(text="Image generated"))
                self.root.after(0, lambda: self.display_message("assistant", f"I generated an image for: '{prompt}'", store=True))
                self.root.after(0, lambda: setattr(self, 'processing', False))
                self.root.after(0, lambda: self.send_btn.config(state="normal"))
                if hasattr(self, 'listen_btn'):
                    self.root.after(0, lambda: self.listen_btn.config(state="normal"))
            threading.Thread(target=gen_thread, daemon=True).start()
            return

        attach_text = ""
        for path in self.attachments:
            fname = os.path.basename(path)
            content = extract_text_from_file(path)
            if content is not None:
                attach_text += f"\n\n[Attached file: {fname}]\n{content}\n"
            else:
                attach_text += f"\n\n[Attached file: {fname}] (content not readable)"

        full_msg = msg + attach_text

        self.entry.delete(0, tk.END)
        self.send_btn.config(state="disabled")
        if hasattr(self, 'listen_btn'):
            self.listen_btn.config(state="disabled")
        self.processing = True
        self.status.config(text="Gyani Baba is thinking...")

        self.display_message("user", msg, attachments=self.attachments)
        self.show_typing()

        self.attachments = []
        self.update_attachment_preview()

        def on_chunk(chunk):
            if chunk is None:
                self.root.after(0, self._finish)
                return
            self.chat.config(state="normal")
            self.chat.insert(tk.END, chunk)
            self.chat.see(tk.END)
            self.chat.config(state="disabled")

        def on_image(image_path):
            self.root.after(0, lambda: self.show_image_preview(image_path))

        def target():
            full = self.llm.send_message(full_msg, on_chunk, on_image=on_image)
            self.last_response = full or ""

        threading.Thread(target=target, daemon=True).start()

    def _finish(self):
        self.hide_typing()
        self.chat.config(state="normal")
        self.chat.insert(tk.END, "\n")
        self.chat.see(tk.END)
        self.chat.config(state="disabled")

        self.send_btn.config(state="normal")
        if hasattr(self, 'listen_btn'):
            self.listen_btn.config(state="normal")
        self.processing = False
        self.status.config(text="Ready")

        if self.tts and self.last_response:
            def speak():
                try:
                    self.tts.say(self.last_response)
                    self.tts.runAndWait()
                except:
                    pass
            threading.Thread(target=speak, daemon=True).start()

    # ============================================================
    # Voice
    # ============================================================
    def listen_voice(self):
        if not VOICE_AVAILABLE:
            messagebox.showerror("Error", "SpeechRecognition not installed.")
            return
        if self.processing:
            return

        if hasattr(self, 'listen_btn'):
            self.listen_btn.config(state="disabled")
        self.status.config(text="Listening...")

        def record():
            recognizer = sr.Recognizer()
            try:
                with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
                    text = recognizer.recognize_google(audio)
                    self.root.after(0, lambda: self._insert_and_send(text))
            except sr.WaitTimeoutError:
                self.root.after(0, lambda: self.status.config(text="No speech detected"))
            except sr.UnknownValueError:
                self.root.after(0, lambda: self.status.config(text="Could not understand"))
            except Exception as e:
                self.root.after(0, lambda: self.status.config(text=f"Error: {e}"))
            finally:
                self.root.after(0, self._enable_listen)

        threading.Thread(target=record, daemon=True).start()

    def _insert_and_send(self, text):
        self.entry.delete(0, tk.END)
        self.entry.insert(0, text)
        self.status.config(text="Transcribed")
        self.send()

    def _enable_listen(self):
        if hasattr(self, 'listen_btn'):
            self.listen_btn.config(state="normal")
        if not self.processing:
            self.status.config(text="Ready")

# ============================================================
# Entry point
# ============================================================
if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = GyaniApp(root)
        root.mainloop()
    except Exception as e:
        try:
            import tkinter.messagebox as mb
            mb.showerror("Fatal Error", f"An error occurred:\n\n{str(e)}\n\nThe app will now close.")
        except:
            import sys
            print(f"Fatal error: {e}", file=sys.stderr)