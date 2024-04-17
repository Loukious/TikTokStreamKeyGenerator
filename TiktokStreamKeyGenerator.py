import tkinter as tk
from tkinter import messagebox, ttk
import json
import os
import threading
import undetected_chromedriver as uc
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests

class Stream:
    def __init__(self, title, game_tag_id, gen_replay=False, close_room_when_close_stream=True, age_restricted=False, priority_region=""):
        self.streamInfo = self.createStream( title, game_tag_id, gen_replay, close_room_when_close_stream, age_restricted, priority_region)
        self.created = False
        try:
            self.streamUrl = self.streamInfo["data"]["stream_url"]["rtmp_push_url"]
            split_index = self.streamUrl.rfind("/")
            self.baseStreamUrl = self.streamUrl[:split_index]
            self.streamKey = self.streamUrl[split_index + 1:]
            self.streamShareUrl = self.streamInfo["data"]["share_url"]
            self.created = True
        except:
            print(self.streamInfo["data"]["prompts"])


    def createStream(self, title, game_tag_id, gen_replay=False, close_room_when_close_stream=True, age_restricted=False, priority_region=""):
        url = "https://webcast16-normal-c-useast2a.tiktokv.com/webcast/room/create/" # comment this line and uncomment the one below if this url doesn't work
        # url = "https://webcast16-normal-c-useast1a.tiktokv.com/webcast/room/create/" 
        params = {
            "aid": "8311", # App ID for TikTok Live Studio
            "app_name": "tiktok_live_studio", # App name for TikTok Live Studio
            "channel": "studio", # Channel for TikTok Live Studio
            "device_platform": "windows",
            "priority_region": priority_region, # Priority region for the stream
            "live_mode": "6"
        }
        data = {
            "title": title, # Title of stream
            "live_studio": "1",
            "gen_replay": gen_replay, # To generate replay
            "close_room_when_close_stream": close_room_when_close_stream, # To close room when stream is closed
            "hashtag_id": "5", # Gaming hashtag ID
            "game_tag_id": game_tag_id # Game ID find more at https://webcast16-normal-c-useast2a.tiktokv.com/webcast/room/hashtag/list/
        }
        if age_restricted:
            data["age_restricted"] = "4"
        headers = {
            "user-agent": ""
        }
        with open('cookies.json', 'r') as file:
            cookies_file = json.load(file)
        cookies = {}
        for cookie in cookies_file:
            cookies[cookie['name']] = cookie['value']

        with requests.session() as s:
            info = s.post(url, params=params, data=data, headers=headers, cookies=cookies, verify=False).json()
        return info

def save_config():
    """Save entry values to a JSON file."""
    data = {
        'title': title_entry.get(),
        'game_tag_id': game_tag_entry.get(),
        'priority_region': region_entry.get(), 
        'generate_replay': replay_var.get(),
        'close_room_when_close_stream': close_room_var.get(),
        'age_restricted': age_restricted_var.get()
    }
    with open('config.json', 'w') as file:
        json.dump(data, file)

def load_config():
    """Load entry values from a JSON file."""
    try:
        with open('config.json', 'r') as file:
            data = json.load(file)
        title_entry.insert(0, data['title'])
        game_tag_entry.insert(0, data['game_tag_id'])
        region_entry.set(data['priority_region'])
        replay_var.set(data['generate_replay'])
        close_room_var.set(data['close_room_when_close_stream'])
        age_restricted_var.set(data['age_restricted'])
    except FileNotFoundError:
        print("No configuration file found. Using defaults.")

def check_cookies():
    """Update the label based on the existence of cookies.json."""
    if os.path.exists('cookies.json'):
        cookies_status.config(text="Cookies are loaded")
        go_live_button.config(state=tk.NORMAL)
        login_button.config(state=tk.DISABLED)
    else:
        cookies_status.config(text="No cookies found")
        go_live_button.config(state=tk.DISABLED)
        login_button.config(state=tk.NORMAL)

def wait_for_page_load(driver, timeout=30):
    """Wait for the page's load state to be 'complete'."""
    return WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )

def launch_browser():
    """Launch Selenium to perform login and save cookies."""
    driver = uc.Chrome()
    driver.get('https://www.tiktok.com/login/phone-or-email')
    try:
        WebDriverWait(driver, 60).until(
            EC.url_contains("https://www.tiktok.com/foryou"))
        cookies = driver.get_cookies()
        with open('cookies.json', 'w') as file:
            json.dump(cookies, file)
        wait_for_page_load(driver)
        driver.quit()
        messagebox.showinfo("Login Status", "Login Successful and cookies saved!")
    except:
        messagebox.showinfo("Login Status", "Login Failed or Timed Out")
    finally:
        driver.quit()
        check_cookies()

def generate_stream():
    """Function for stream key generation."""
    server_entry.config(state=tk.NORMAL)
    key_entry.config(state=tk.NORMAL)
    url_entry.config(state=tk.NORMAL)

    s = Stream(title_entry.get(), game_tag_entry.get(), replay_var.get(), close_room_var.get(), age_restricted_var.get(), region_entry.get())
    if s.created:
        server_entry.delete(0, tk.END)
        server_entry.insert(0, s.baseStreamUrl)
        key_entry.delete(0, tk.END)
        key_entry.insert(0, s.streamKey)
        url_entry.delete(0, tk.END)
        url_entry.insert(0, s.streamShareUrl)
    else:
        server_entry.delete(0, tk.END)
        key_entry.delete(0, tk.END)
        url_entry.delete(0, tk.END)
        messagebox.showerror("Error", "Failed to create stream")

    server_entry.config(state=tk.DISABLED)
    key_entry.config(state=tk.DISABLED)
    url_entry.config(state=tk.DISABLED)

def login_thread():
    """Handle the login process in a separate thread to keep UI responsive."""
    threading.Thread(target=launch_browser).start()

app = tk.Tk()
app.title("TikTok Stream Key Generator")

# Input fields and labels
tk.Label(app, text="Title").grid(row=0, column=0)
title_entry = tk.Entry(app, width=30)
title_entry.grid(row=0, column=1)
title_entry.bind('<FocusOut>', lambda e: save_config())

tk.Label(app, text="Game Tag ID").grid(row=1, column=0)
game_tag_entry = tk.Entry(app)
game_tag_entry.grid(row=1, column=1)
game_tag_entry.bind('<FocusOut>', lambda e: save_config())

tk.Label(app, text="Region").grid(row=2, column=0)
region_entry = ttk.Combobox(app, values=["", "ar", "bg", "bn-IN", "ceb-PH", "cs-CZ", "da", "de-DE", "el-GR", "en", "es", "et", "fi-FI", "fil-PH", "fr", "he-IL", "hi-IN", "hr", "hu-HU", "id-ID", "it-IT", "ja-JP", "jv-ID", "km-KH", "ko-KR", "lt", "lv", "ms-MY", "my-MM", "nb", "nl-NL", "pl-PL", "pt-BR", "ro-RO", "ru-RU", "sk", "sv-SE", "th-TH", "tr-TR", "uk-UA", "ur", "uz", "vi-VN", "zh-Hant-TW", "zh-Hans"])
region_entry.grid(row=2, column=1)


replay_var = tk.BooleanVar()
tk.Checkbutton(app, text="Generate Replay", variable=replay_var).grid(row=3, column=0, columnspan=2)

close_room_var = tk.BooleanVar(value=True)
tk.Checkbutton(app, text="Close Room When Close Stream", variable=close_room_var).grid(row=4, column=0, columnspan=2)

age_restricted_var = tk.BooleanVar()
tk.Checkbutton(app, text="Age Restricted", variable=age_restricted_var).grid(row=5, column=0, columnspan=2)

# Cookies status
cookies_status = tk.Label(app, text="Checking cookies...")
cookies_status.grid(row=6, column=0, columnspan=2)

# Buttons
login_button = tk.Button(app, text="Login", command=login_thread, state=tk.DISABLED)
login_button.grid(row=7, column=0)

go_live_button = tk.Button(app, text="Go Live", command=generate_stream, state=tk.DISABLED)
go_live_button.grid(row=7, column=1)

save_config_button = tk.Button(app, text="Save Config", command=save_config)
save_config_button.grid(row=7, column=2)

check_cookies()
load_config()
# Outputs
server_entry = tk.Entry(app, state="readonly", width=50)
server_entry.grid(row=8, column=0, columnspan=2)

key_entry = tk.Entry(app, state="readonly", width=50)
key_entry.grid(row=9, column=0, columnspan=2)

url_entry = tk.Entry(app, state="readonly", width=50)
url_entry.grid(row=10, column=0, columnspan=2)
url_entry.grid(row=10, column=0, columnspan=2)

def copy_to_clipboard(content):
    app.clipboard_clear()
    app.clipboard_append(content)
    messagebox.showinfo("Copied", "Content copied to clipboard!")

# Copy buttons for each Entry
copy_server_button = tk.Button(app, text="Copy", command=lambda: copy_to_clipboard(server_entry.get()))
copy_server_button.grid(row=8, column=2)

copy_key_button = tk.Button(app, text="Copy", command=lambda: copy_to_clipboard(key_entry.get()))
copy_key_button.grid(row=9, column=2)

copy_url_button = tk.Button(app, text="Copy", command=lambda: copy_to_clipboard(url_entry.get()))
copy_url_button.grid(row=10, column=2)

app.mainloop()
