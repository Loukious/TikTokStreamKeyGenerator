import hashlib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
import threading
import undetected_chromedriver as uc
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
import time
from urllib.parse import urlencode
import urllib.parse
from Libs.device import Device
from Libs.device_gen import Applog, Xlog
from Libs.XGorgon import XGorgon
from Libs.signature import ladon_encrypt
from Libs.XArgus import Argus




class Stream:
    def __init__(self):
        self.s = requests.session()
        with open("cookies.json", "r") as file:
            cookies_file = json.load(file)
        cookies = {}
        for cookie in cookies_file:
            cookies[cookie["name"]] = cookie["value"]
        self.s.cookies.update(cookies)
        # self.renewCookies()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.s.close()
    
    def getLiveStudioLatestVersion(self):
        url = "https://tron-sg.bytelemon.com/api/sdk/check_update"
        params = {
            "pid": "7393277106664249610",
            "uid": "7464643088460875280",
            "branch": "studio/release/stable",
            "buildId": "0"
        }
        try:
            with self.s.get(url, params=params, verify=False) as response:
                return response.json()["data"]["manifest"]["win32"]["version"]
        except Exception as e:
            print(f"Failed to fetch latest version: {e}")
            return "0.99.0"
        

    def createStream(
        self,
        title,
        hashtag_id,
        game_tag_id="0",
        gen_replay=False,
        close_room_when_close_stream=True,
        age_restricted=False,
        priority_region="",
        thumbnail_path = ""
    ):
        base_url = self.getServerUrl()
        print(base_url)
        
        # Use TikTok Live Studio
        version = self.getLiveStudioLatestVersion()
        # App ID for TikTok Live Studio
        aid = "8311"
        self.s.headers = {
            "user-agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) TikTokLIVEStudio/{version} Chrome/136.0.7103.59 Electron/36.4.0-rs.18.release.ls.26 TTElectron/36.4.0-rs.18.release.ls.26 Safari/537.36",
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site",
            "sec-fetch-storage-access": "active",
            "x-ss-dp": "",
            "sdk_aid": aid,
            "sec-ch-ua": '"Not.A/Brand";v="99", "Chromium";v="136"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        params = {
            "aid": aid,
            # App name for TikTok Live Studio
            "app_name": "tiktok_live_studio",
            "device_id": "7598549125457659393",
            "install_id": "7598551635623053072",
            # Channel for TikTok Live Studio
            "channel": "studio",
            "version_code": version,
            "device_platform": "windows",
            "timezone_name": "Africa/Tunis",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "en-US",
            "browser_platform": "Win32",
            "browser_name": "Mozilla",
            "browser_version": f"5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) TikTokLIVEStudio/{version} Chrome/136.0.7103.59 Electron/36.4.0-rs.18.release.ls.26 TTElectron/36.4.0-rs.18.release.ls.26 Safari/537.36",
            "language": "en",
            "app_language": "en",
            "webcast_language": "en",
            # Priority region for the stream
            "priority_region": priority_region,
            "webcast_sdk_version": version.replace(".", ""),
            "live_mode": "6",
        }
        data = {
            self.s.headers = {
                "user-agent": "com.zhiliaoapp.musically/2023508030 (Linux; U; Android 14; en_US_#u-mu-celsius; M2102J20SG; Build/AP2A.240905.003; Cronet/TTNetVersion:f58efab5 2024-06-13 QuicVersion:5d23606e 2024-05-23)",
            }
            params = {
                # App ID for Tiktok Mobile App
                "aid": "1233",
                # App name for Tiktok Mobile App
                "app_name": "musical_ly",
                # Channel for Tiktok Mobile App
                "channel": "googleplay",
                "device_platform": "android",
                "iid": iid,
                "device_id": device_id,
                "openudid": openudid,
                "screen_shot": "1",
                "ac": "wifi",
                "version_code": "370104",
                "version_name": "37.1.4",
                "os": "android",
                "ab_version": "37.1.4",
                "ssmix": "a",
                "device_type": "M2102J20SG",
                "device_brand": "POCO",
                "language": "en",
                "os_api": "34",
                "os_version": "14",
                "manifest_version_code": "2023701040",
                "resolution": "1080*2309",
                "dpi": "410",
                "update_version_code": "2023701040",
                "_rticket": "1730306440278",
                "is_pad": "0",
                "current_region": "TN",
                "app_type": "normal",
                "sys_region": "US",
                "last_install_time": "1730305998",
                "mcc_mnc": "60501",
                "timezone_name": "Africa/Tunis",
                "carrier_region_v2": "605",
                "residence": "TN",
                "app_language": "en",
                "carrier_region": "TN",
                "ac2": "wifi5g",
                "uoo": "0",
                "op_region": "TN",
                "timezone_offset": "3600",
                "build_number": "37.1.4",
                "host_abi": "arm64-v8a",
                "locale": "en",
                "region": "US",
                "ts": "1730306440",
                "cdid": "bfe31618-558b-4e0d-a4e5-c4221be305a1",
                "webcast_sdk_version": "3490",
                "webcast_language": "en",
                "webcast_locale": "en_US_#u-mu-celsius",
                "es_version": "2",
                "effect_sdk_version": "17.0.0",
                "current_network_quality_info": '{"tcp_rtt":99,"quic_rtt":99,"http_rtt":203,"downstream_throughput_kbps":2734,"quic_send_loss_rate":-1,"quic_receive_loss_rate":-1,"net_effective_connection_type":4,"video_download_speed":7}'
            }
            data = {
                "hashtag_id": hashtag_id,
                "hold_living_room": "1",
                "chat_sub_only_auth": "2",
                "screen_shot": "1",
                "mute_duration": "1",
                "community_flagged_chat_auth": "2",
                "ecom_bc_toggle": "3",
                "live_sub_only": "0",
                "chat_l_2": "1",
                "caption": "0",
                "live_sub_only_use_music": "0",
                "mobile_binded": "0",
                "create_source": "0",
                "spam_comments": "1",
                "commercial_content_promote_third_party": "false",
                "grant_level": "0",
                "screenshot_cover_status": "1",
                "enable_http_dns": "0",
                "mobile_validated": "0",
                "live_agreement": "0",
                "orientation": "2",
                "commercial_content_promote_myself": "false",
                "allow_preview_duration_exp": "0",
                "transaction_history": "1",
                "chat_auth": "1",
                "disable_preview_sub_only": "0",
                "comment_tray_switch": "1",
                "grant_group": "1",
                "gift_auth": "1",
                "star_comment_switch": "true",
                "has_commerce_goods": "false",
                "open_commercial_content_toggle": "false",
                "event_id": "-1",
                "star_comment_qualification": "true",
                "game_tag_id": game_tag_id,
                "community_flagged_chat_review_auth": "2",
                "age_restricted": "0",
                "sdk_key": "hd",
                "live_room_mode": "4",
                "gen_replay": str(gen_replay).lower(),
                "shopping_ranking": "0"
            }
        else:
            version = self.getLiveStudioLatestVersion()
            # App ID for TikTok Live Studio
            aid = "8311"
            self.s.headers = {
                "user-agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) TikTokLIVEStudio/{version} Chrome/136.0.7103.59 Electron/36.4.0-rs.18.release.ls.26 TTElectron/36.4.0-rs.18.release.ls.26 Safari/537.36",
                "accept": "application/json, text/plain, */*",
                "accept-language": "en-US",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "cross-site",
                "sec-fetch-storage-access": "active",
                "x-ss-dp": "",
                "sdk_aid": aid,
                "sec-ch-ua": '"Not.A/Brand";v="99", "Chromium";v="136"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }
            params = {
                "aid": aid,
                # App name for TikTok Live Studio
                "app_name": "tiktok_live_studio",
                "device_id": "7598549125457659393",
                "install_id": "7598551635623053072",
                # Channel for TikTok Live Studio
                "channel": "studio",
                "version_code": version,
                "device_platform": "windows",
                "timezone_name": "Africa/Tunis",
                "screen_width": "1920",
                "screen_height": "1080",
                "browser_language": "en-US",
                "browser_platform": "Win32",
                "browser_name": "Mozilla",
                "browser_version": f"5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) TikTokLIVEStudio/{version} Chrome/136.0.7103.59 Electron/36.4.0-rs.18.release.ls.26 TTElectron/36.4.0-rs.18.release.ls.26 Safari/537.36",
                "language": "en",
                "app_language": "en",
                "webcast_language": "en",
                # Priority region for the stream
                "priority_region": priority_region,
                "webcast_sdk_version": version.replace(".", ""),
                "live_mode": "6",
            }
            data = {
                "title": title,
                "live_studio": "1",
                "gen_replay": str(gen_replay).lower(),
                "chat_auth": "1",
                "age_restricted": "0",
                "cover_uri": "",
                "close_room_when_close_stream": str(close_room_when_close_stream).lower(),
                "hashtag_id": str(hashtag_id),
                "game_tag_id": str(game_tag_id),
                "screenshot_cover_status": "1",
                "live_sub_only": "0",
                "chat_sub_only_auth": "2",
                "multi_stream_scene": "0",
                "gift_auth": "1",
                "chat_l2": "1",
                "star_comment_switch": "true",
                "multi_stream_source": "1",
                "is_group_live_session": "false",
                "open_commercial_content_toggle": "false",
                "commercial_content_promote_myself": "false",
                "commercial_content_promote_third_party": "false",
            }
        if age_restricted:
            data["age_restricted"] = "4"
        if thumbnail_path:
            uri = self.uploadThumbnail(thumbnail_path, base_url, params)
            data["cover_uri"] = uri
        
        # Build the URL encoded body for signing
        body_encoded = urlencode(data)
        
        # Generate signing headers for Live Studio requests
        if spoof_plat == 0:
            # Get current timestamp for signing
            timestamp = int(time.time())
            
            # Calculate x-ss-stub (MD5 hash of the POST body)
            x_ss_stub = hashlib.md5(body_encoded.encode()).hexdigest()
            
            # Generate x-ladon signature
            x_ladon = ladon_encrypt(
                timestamp=timestamp,
                license_id=1611921764,
                aid=int(params["aid"])
            )
            
            # Build query string for x-argus
            query_string = urlencode(params)
            
            # Generate x-argus signature
            x_argus = Argus.get_sign(
                params=query_string,
                stub=x_ss_stub,
                timestamp=timestamp,
                aid=int(params["aid"]),
                license_id=1611921764,
                platform=0,  # Windows
                channel=params.get("channel", "studio"),
            )
            
            # Add signing headers
            self.s.headers["x-ss-stub"] = x_ss_stub
            self.s.headers["x-khronos"] = str(timestamp)
            self.s.headers["x-ladon"] = x_ladon
            self.s.headers["x-argus"] = x_argus
            
        streamInfo = self.s.post(
            base_url + "webcast/room/create/",
            params=params,
            data=data,
            verify=False
        ).json()
        try:
            self.streamUrl = streamInfo["data"]["stream_url"][
                "rtmp_push_url"
            ]
            split_index = self.streamUrl.rfind("/")
            self.baseStreamUrl = self.streamUrl[:split_index]
            self.streamKey = self.streamUrl[split_index + 1:]
            self.streamShareUrl = streamInfo["data"]["share_url"]
            return True
        except KeyError:
            messagebox.showerror(
                "Error", streamInfo["data"]["prompts"]
            )
            return False

    def endStream(self):
        base_url = self.getServerUrl()
        params = {
            # App ID for TikTok Live Studio
            "aid": "8311",
            # App name for TikTok Live Studio
            "app_name": "tiktok_live_studio",
            # Channel for TikTok Live Studio
            "channel": "studio",
            "device_platform": "windows",
            "live_mode": "6",
        }
        streamInfo = self.s.post(
            base_url + "webcast/room/finish_abnormal/",
            params=params,
            verify=False
        ).json()
        if "data" in streamInfo and "prompts" in streamInfo["data"]:
            messagebox.showerror(
                "Error", streamInfo["data"]["prompts"]
            )
            return False
        return True

    def getServerUrl(self):
        url = (
            "https://tnc16-platform-useast1a.tiktokv.com/get_domains/v4/?"
            "aid=8311&ttwebview_version=1130022001&device_platform=win"
        )
        response = self.s.get(url, verify=False).json()
        for data in response["data"]["ttnet_dispatch_actions"]:
            if "param" in data and "strategy_info" in data["param"] and "webcast-normal.tiktokv.com" in data["param"]["strategy_info"]:
                server_url = data['param']['strategy_info']['webcast-normal.tiktokv.com']
                for data2 in response["data"]["ttnet_dispatch_actions"]:
                    if "param" in data2 and "strategy_info" in data2["param"] and server_url in data2["param"]["strategy_info"]:
                        server_url = data2['param']['strategy_info'][server_url]
                        return f"https://{server_url}/"
                return f"https://{server_url}/"
            
    def uploadThumbnail(
        self,
        file_path,
        base_url,
        params
    ):
        files = {
            "file": (f"crop_{round(time.time() * 1000)}.png", open(file_path, "rb"), "multipart/form-data")
        }
        thumbnailInfo = self.s.post(
                    base_url + "webcast/room/upload/image/",
                    params=params,
                    files=files,
                    verify=False
        ).json()
        return thumbnailInfo.get("data", {}).get("uri", "")
            
    def renewCookies(self):
        response = self.s.get("https://www.tiktok.com/foryou")
        if response.url == "https://www.tiktok.com/login/phone-or-email":
            messagebox.showerror(
                "Error", "Cookies are invalid. Please login again."
            )
            cookies_status.config(text="No cookies found")
            go_live_button.config(state=tk.DISABLED)
            login_button.config(state=tk.NORMAL)
            os.remove("cookies.json")
            return False
        else:
            new_cookies = []
            cookies = dict(self.s.cookies)
            for cookie in cookies:
                new_cookies.append(
                    {
                        "name": cookie,
                        "value": cookies[cookie]
                    }
                )
            with open("cookies.json", "w") as file:
                json.dump(new_cookies, file)
            return True


def save_config():
    """Save entry values to a JSON file."""
    if game_combobox.get() != "":
        game_id = [
            game for game in games
            if games[game].lower() == game_combobox.get().lower()
        ][0]
    else:
        game_id = ""
    if topic_combobox.get() != "":
        topic_id = [
            topic for topic in topics
            if topics[topic].lower() == topic_combobox.get().lower()
        ][0]
    else:
        topic_id = ""

    data = {
        "title": title_entry.get(),
        "game_tag_id": game_id,
        "hashtag_id": topic_id,
        "priority_region": region_entry.get(),
        "generate_replay": replay_var.get(),
        "spoof_plat": spoof_plat_var.get(),
        "close_room_when_close_stream": close_room_var.get(),
        "age_restricted": age_restricted_var.get(),
        "openudid": openudid_entry.get(),
        "device_id": device_id_entry.get(),
        "iid": iid_entry.get()
    }
    with open("config.json", "w") as file:
        json.dump(data, file)
    messagebox.showinfo("Success", "Config saved successfully.")
    return True


def load_config():
    """Load entry values from a JSON file."""
    try:
        with open("config.json", "r") as file:
            data = json.load(file)
        title_entry.delete(0, tk.END)
        title_entry.insert(0, data.get("title", ""))
        topic_combobox.set(topics.get(data.get("hashtag_id", ""), ""))
        if topic_combobox.get() != "Gaming":
            game_combobox.grid_remove()
            game_label.grid_remove()
        else:
            game_combobox.set(games.get(data.get("game_tag_id", ""), ""))
        region_entry.set(data.get("priority_region", ""))
        replay_var.set(data.get("generate_replay", False))
        spoof_plat_var.set(data.get("spoof_plat", 0))
        openudid_entry.delete(0, tk.END)
        openudid_entry.insert(0, data.get("openudid", ""))
        device_id_entry.delete(0, tk.END)
        device_id_entry.insert(0, data.get("device_id", ""))
        iid_entry.delete(0, tk.END)
        iid_entry.insert(0, data.get("iid", ""))
        if spoof_plat_var.get() == 0:
            spoofing_frame.grid_remove()
        close_room_var.set(data.get("close_room_when_close_stream", True))
        age_restricted_var.set(data.get("age_restricted", False))
    except FileNotFoundError:
        print("Error loading config file.")


def check_cookies():
    """Update the label based on the existence of cookies.json."""
    if os.path.exists("cookies.json"):
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
    driver.get("https://www.tiktok.com/login?is_modal=1&hide_toggle_login_signup=1&enter_method=live_studio&enter_from=live_studio&lang=en")
    try:
        WebDriverWait(driver, 60).until(
            EC.url_contains("https://www.tiktok.com/foryou")
        )
        cookies = driver.get_cookies()
        with open("cookies.json", "w") as file:
            json.dump(cookies, file)
        wait_for_page_load(driver)
        driver.quit()
        messagebox.showinfo(
            "Login Status", "Login Successful and cookies saved!"
        )
    except Exception as e:
        error_message = f"Login Failed or Timed Out.\n" \
                        f"Error type: {type(e).__name__}, Message: {str(e)}"
        messagebox.showinfo("Login Status", error_message)
    finally:
        driver.quit()
        check_cookies()


def enable_output_fields():
    """Enable output fields after stream is generated."""
    server_entry.config(state=tk.NORMAL)
    key_entry.config(state=tk.NORMAL)
    url_entry.config(state=tk.NORMAL)


def disable_output_fields():
    """Disable output fields when stream is not generated."""
    server_entry.config(state=tk.DISABLED)
    key_entry.config(state=tk.DISABLED)
    url_entry.config(state=tk.DISABLED)


def clear_output_fields():
    """Clear output fields."""
    server_entry.delete(0, tk.END)
    key_entry.delete(0, tk.END)
    url_entry.delete(0, tk.END)


def end_stream():
    """End the current stream."""
    with Stream() as s:
        ended = s.endStream()
        if ended:
            messagebox.showinfo("Success", "Stream ended successfully.")
            enable_output_fields()
            clear_output_fields()
            disable_output_fields()


def generate_stream():
    """Function for stream key generation."""
    if topic_combobox.get() != "":
        hashtag_id = [
            topic for topic in topics
            if topics[topic].lower() == topic_combobox.get().lower()
        ][0]
    else:
        messagebox.showerror("Error", "Please select a topic.")
        return
    if hashtag_id == "5" and game_combobox.get() == "":
        messagebox.showerror("Error", "Please select a game tag.")
        return
    if hashtag_id != "5":
        game_id = "0"
    else:
        game_id = [
            game for game in games
            if games[game].lower() == game_combobox.get().lower()
        ][0]
    with Stream() as s:
        created = s.createStream(
            title_entry.get(),
            hashtag_id,
            game_id,
            replay_var.get(),
            close_room_var.get(),
            age_restricted_var.get(),
            region_entry.get(),
            spoof_plat_var.get(),
            openudid_entry.get(),
            device_id_entry.get(),
            iid_entry.get(),
            thumbnail_path_var.get()
        )
        if created:
            messagebox.showinfo("Success", "Stream created successfully.")
            enable_output_fields()
            clear_output_fields()
            server_entry.insert(0, s.baseStreamUrl)
            key_entry.insert(0, s.streamKey)
            url_entry.insert(0, s.streamShareUrl)
            disable_output_fields()


def login_thread():
    """Handle the login process in a separate thread to keep UI responsive."""
    threading.Thread(target=launch_browser).start()


def fetch_game_tags():
    url = (
        "https://webcast16-normal-c-useast2a.tiktokv.com/webcast/"
        "room/hashtag/list/"
    )
    try:
        response = requests.get(url)
        game_tags = response.json()["data"]["game_tag_list"]
        return {game["id"]: game["show_name"] for game in game_tags}
    except Exception as e:
        print(f"Failed to fetch game tags: {e}")
        return {}


def update_combobox_options(event):
    # Get current text in the combobox
    current_text = game_combobox.get()
    # Filter the games dictionary
    filtered_options = [
        name
        for name in games.values()
        if name.lower().startswith(current_text.lower())
    ]
    # Update the options displayed in the combobox
    game_combobox["values"] = filtered_options


def check_selection(event):
    if topic_combobox.get() == "Gaming":
        game_combobox.grid(row=2, column=1, padx=5, pady=2, sticky="ew")
        game_label.grid(row=2, column=0, padx=5, pady=2, sticky="w")
    else:
        game_combobox.grid_remove()
        game_label.grid_remove()


def on_spoof_plat_change(*args):
    selected_value = spoof_plat_var.get()
    if selected_value == 0:
        spoofing_frame.grid_remove()
    else:
        spoofing_frame.grid()

def browse_image():
    file_path = filedialog.askopenfilename(
        title="Select a Image",
        filetypes=[("PNG files", "*.png"), ("JPG files", "*.jpg"), ("JPEG files", "*.jpeg"), ("All files", "*.*")]
    )
    if file_path:
        thumbnail_path_var.set(file_path)

def generate_device():
    device: dict = Device().create_device()
    device_id, install_id = Applog(device).register_device()
    Xlog(device_id).bypass()
    openudid_entry.delete(0, tk.END)
    openudid_entry.insert(0, device["openudid"])
    device_id_entry.delete(0, tk.END)
    device_id_entry.insert(0, device_id)
    iid_entry.delete(0, tk.END)
    iid_entry.insert(0, install_id)



topics = {
    "5": "Gaming",
    "6": "Music",
    "42": "Chat & Interview",
    "9": "Beauty & Fashion",
    "3": "Dance",
    "13": "Fitness & Sports",
    "4": "Food",
    "43": "News & Event",
    "45": "Education"
}


app = tk.Tk()
app.title("TikTok Stream Key Generator")
app.columnconfigure(0, weight=1)
app.columnconfigure(1, weight=1)
app.columnconfigure(2, weight=1)

# Using LabelFrames for better organization
input_frame = ttk.LabelFrame(app, text="Input")
input_frame.grid(row=0, column=0, padx=10, pady=5, sticky="nsew")
input_frame.columnconfigure(0, weight=1)

# Input fields and labels inside the LabelFrame
title_label = ttk.Label(input_frame, text="Title")
title_label.grid(row=0, column=0, padx=5, pady=2, sticky="w")

title_entry = ttk.Entry(input_frame)
title_entry.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

topic_label = ttk.Label(input_frame, text="Topic")
topic_label.grid(row=1, column=0, padx=5, pady=2, sticky="w")

topic_combobox = ttk.Combobox(input_frame, values=list(topics.values()))
topic_combobox.grid(row=1, column=1, padx=5, pady=2, sticky="ew")
topic_combobox.bind('<<ComboboxSelected>>', check_selection)

game_combobox = ttk.Combobox(input_frame)

game_label = ttk.Label(input_frame, text="Game")
game_label.grid(row=2, column=0, padx=5, pady=2, sticky="w")

games = fetch_game_tags()
game_combobox = ttk.Combobox(input_frame, values=list(games.values()))
game_combobox.grid(row=2, column=1, padx=5, pady=2, sticky="ew")
game_combobox.bind("<KeyRelease>", update_combobox_options)

region_label = ttk.Label(input_frame, text="Region")
region_label.grid(row=3, column=0, padx=5, pady=2, sticky="w")

region_entry = ttk.Combobox(
    input_frame,
    values=[
        "", "af", "ax", "al", "dz", "as", "ad", "ao", "ai", "aq", "ag", "ar", "am", "aw", "au",
        "at", "az", "bs", "bh", "bd", "bb", "by", "be", "bz", "bj", "bm", "bt", "bo", "bq",
        "ba", "bw", "bv", "br", "io", "bn", "bg", "bf", "bi", "cv", "kh", "cm", "ca", "ky",
        "cf", "td", "cl", "cn", "cx", "cc", "co", "km", "cg", "cd", "ck", "cr", "ci", "hr",
        "cu", "cw", "cy", "cz", "dk", "dj", "dm", "do", "ec", "eg", "sv", "gq", "er", "ee",
        "sz", "et", "fk", "fo", "fj", "fi", "fr", "gf", "pf", "tf", "ga", "gm", "ge", "de",
        "gh", "gi", "gr", "gl", "gd", "gp", "gu", "gt", "gg", "gn", "gw", "gy", "ht", "hm",
        "va", "hn", "hk", "hu", "is", "in", "id", "ir", "iq", "ie", "im", "il", "it", "jm",
        "jp", "je", "jo", "kz", "ke", "ki", "kp", "kr", "kw", "kg", "la", "lv", "lb", "ls",
        "lr", "ly", "li", "lt", "lu", "mo", "mg", "mw", "my", "mv", "ml", "mt", "mh", "mq",
        "mr", "mu", "yt", "mx", "fm", "md", "mc", "mn", "me", "ms", "ma", "mz", "mm", "na",
        "nr", "np", "nl", "nc", "nz", "ni", "ne", "ng", "nu", "nf", "mk", "mp", "no", "om",
        "pk", "pw", "ps", "pa", "pg", "py", "pe", "ph", "pn", "pl", "pt", "pr", "qa", "re",
        "ro", "ru", "rw", "bl", "sh", "kn", "lc", "mf", "pm", "vc", "ws", "sm", "st", "sa",
        "sn", "rs", "sc", "sl", "sg", "sx", "sk", "si", "sb", "so", "za", "gs", "ss", "es",
        "lk", "sd", "sr", "sj", "se", "ch", "sy", "tw", "tj", "tz", "th", "tl", "tg", "tk",
        "to", "tt", "tn", "tr", "tm", "tc", "tv", "ug", "ua", "ae", "gb", "um", "us", "uy",
        "uz", "vu", "ve", "vn", "vg", "vi", "wf", "eh", "ye", "zm", "zw"
    ],
)
region_entry.grid(row=3, column=1, padx=5, pady=2, sticky="ew")


spoof_plat_var = tk.IntVar()
spoof_plat_var.set(0)
spoof_plat_var.trace_add("write", on_spoof_plat_change)
spoof_plat_radio1 = ttk.Radiobutton(
    input_frame, text="No Spoofing", variable=spoof_plat_var, value=0
)
spoof_plat_radio1.grid(row=4, column=0, columnspan=1, padx=5, pady=2, sticky="w")

spoof_plat_radio2 = ttk.Radiobutton(
    input_frame, text="Mobile Camera Stream (gets no traffic)", variable=spoof_plat_var, value=1
)
spoof_plat_radio2.grid(row=4, column=1, columnspan=1, padx=5, pady=2, sticky="w")

spoof_plat_radio3 = ttk.Radiobutton(
    input_frame, text="Mobile Screenshare (gets no traffic)", variable=spoof_plat_var, value=2
)
spoof_plat_radio3.grid(row=4, column=2, columnspan=1, padx=5, pady=2, sticky="w")

replay_var = tk.BooleanVar()
replay_checkbox = ttk.Checkbutton(
    input_frame, text="Generate Replay", variable=replay_var
)
replay_checkbox.grid(row=5, column=0, columnspan=2, padx=5, pady=2, sticky="w")

close_room_var = tk.BooleanVar(value=True)
close_room_checkbox = ttk.Checkbutton(
    input_frame, text="Close Room When Close Stream", variable=close_room_var
)
close_room_checkbox.grid(
    row=6, column=0, columnspan=2, padx=5, pady=2, sticky="w"
)

age_restricted_var = tk.BooleanVar()
age_restricted_checkbox = ttk.Checkbutton(
    input_frame, text="Age Restricted", variable=age_restricted_var
)
age_restricted_checkbox.grid(
    row=7, column=0, columnspan=2, padx=5, pady=2, sticky="w"
)

# File input
thumbnail_path_var = tk.StringVar()

thumbnail_label = ttk.Label(input_frame, text="Selected Thumbnail:")
thumbnail_label.grid(row=8, column=0, padx=5, pady=5, sticky="w")

thumbnail_entry = ttk.Entry(input_frame, textvariable=thumbnail_path_var, width=50)
thumbnail_entry.grid(row=8, column=1, padx=5, pady=5, sticky="ew")

browse_button = ttk.Button(input_frame, text="Browse", command=browse_image)
browse_button.grid(row=8, column=2, padx=5, pady=5, sticky="ew")

# Using LabelFrames for better organization
spoofing_frame = ttk.LabelFrame(app, text="Spoofing Info")
spoofing_frame.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
spoofing_frame.columnconfigure(1, weight=1)
spoofing_frame.grid_remove()

# Additional fields for Mobile Camera Stream and Mobile Screenshare
openudid_label = ttk.Label(spoofing_frame, text="OpenUDID")
openudid_label.grid(row=0, column=0, padx=5, pady=2, sticky="w")

openudid_entry = ttk.Entry(spoofing_frame)
openudid_entry.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

device_id_label = ttk.Label(spoofing_frame, text="Device ID")
device_id_label.grid(row=1, column=0, padx=5, pady=2, sticky="w")

device_id_entry = ttk.Entry(spoofing_frame)
device_id_entry.grid(row=1, column=1, padx=5, pady=2, sticky="ew")

iid_label = ttk.Label(spoofing_frame, text="IID")
iid_label.grid(row=2, column=0, padx=5, pady=2, sticky="w")

iid_entry = ttk.Entry(spoofing_frame)
iid_entry.grid(row=2, column=1, padx=5, pady=2, sticky="ew")

create_device_button = ttk.Button(
    spoofing_frame, text="Generate Device", command=generate_device
)
create_device_button.grid(row=3, column=0, padx=10, pady=5, sticky="ew")


cookies_frame = ttk.LabelFrame(app, text="Cookies Info")
cookies_frame.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
cookies_frame.columnconfigure(1, weight=1)

# Cookies status
cookies_status = ttk.Label(cookies_frame, text="Checking cookies...")
cookies_status.grid(row=1, column=0, padx=10, pady=5, sticky="ew")

# Buttons
login_button = ttk.Button(
    app, text="Login", command=login_thread, state=tk.DISABLED
)
login_button.grid(row=3, column=0, padx=10, pady=5, sticky="ew")

go_live_button = ttk.Button(
    app, text="Go Live", command=generate_stream, state=tk.DISABLED
)
go_live_button.grid(row=4, column=0, padx=10, pady=5, sticky="ew")

end_live_button = ttk.Button(
    app, text="End Live", command=end_stream
)
end_live_button.grid(row=5, column=0, padx=10, pady=5, sticky="ew")

save_config_button = ttk.Button(app, text="Save Config", command=save_config)
save_config_button.grid(row=6, column=0, padx=10, pady=5, sticky="ew")

# Outputs
output_frame = ttk.LabelFrame(app, text="Outputs")
output_frame.grid(row=0, column=1, rowspan=5, padx=10, pady=5, sticky="nsew")
output_frame.columnconfigure(0, weight=1)

server_entry = ttk.Entry(output_frame, state="readonly")
server_entry.grid(row=0, column=0, padx=5, pady=2, sticky="ew")

key_entry = ttk.Entry(output_frame, state="readonly")
key_entry.grid(row=1, column=0, padx=5, pady=2, sticky="ew")

url_entry = ttk.Entry(output_frame, state="readonly")
url_entry.grid(row=2, column=0, padx=5, pady=2, sticky="ew")


def copy_to_clipboard(content):
    app.clipboard_clear()
    app.clipboard_append(content)
    messagebox.showinfo("Copied", "Content copied to clipboard!")


# Copy buttons for each Entry
copy_server_button = ttk.Button(
    output_frame,
    text="Copy",
    command=lambda: copy_to_clipboard(server_entry.get()),
)
copy_server_button.grid(row=0, column=1, padx=5, pady=2)

copy_key_button = ttk.Button(
    output_frame,
    text="Copy",
    command=lambda: copy_to_clipboard(key_entry.get()),
)
copy_key_button.grid(row=1, column=1, padx=5, pady=2)

copy_url_button = ttk.Button(
    output_frame,
    text="Copy",
    command=lambda: copy_to_clipboard(url_entry.get()),
)
copy_url_button.grid(row=2, column=1, padx=5, pady=2)

check_cookies()
load_config()

app.mainloop()
