import json, time, hashlib, requests

from urllib.parse import *
from .constants import *
from .ttencrypt import TTEncrypt
from .xgorgon import Xgorgon




class Applog:
    def __init__(self, device: dict, proxy = None):
        self.__device = device
        self.__host = "log-va.tiktokv.com"

    def __headers(self, params: str, payload: (str or bool) = None) -> dict: # type: ignore
        sig = Xgorgon().calculate(params, payload, None)

        headers = {
            "x-ss-stub": str(hashlib.md5(str(payload).encode()).hexdigest()).upper(),
            "accept-encoding": "gzip",
            "passport-sdk-version": "19",
            "sdk-version": "2",
            "x-ss-req-ticket": str(int(time.time())) + "000",
            "x-tt-dm-status": "login=0;ct=0",
            "host": self.__host,
            "connection": "Keep-Alive",
            "content-type": "application/octet-stream",
            "user-agent": (
                f"com.zhiliaoapp.musically/{application['version_code']} "
                + f"(Linux; U; Android {self.__device['os']}; pt_BR; {self.__device['device_model']}; "
                + f"Build/{self.__device['build']}; "
                + "Cronet/TTNetVersion:5f9640e3 2021-04-21 QuicVersion:47946d2a 2020-10-14)"
            ),
            "x-gorgon": sig["x-gorgon"],
            "x-khronos": str(sig["x-khronos"]),
        }

        return headers

    def __params(self) -> str:
        __base_params = {
            "ac": "wifi",
            "channel": "googleplay",
            "aid": application["aid"],
            "app_name": "musical_ly",
            "version_code": application["version_code"],
            "version_name": application["version_name"],
            "device_platform": "android",
            "ab_version": application["ab_version"],
            "ssmix": "a",
            "device_type": self.__device["device_model"],
            "device_brand": self.__device["device_brand"],
            "language": self.__device["language"],
            "os_api": self.__device["os_api"],
            "os_version": self.__device["os"],
            "openudid": self.__device["openudid"],
            "manifest_version_code": application["manifest_version_code"],
            "resolution": str(self.__device["resolution"]).split("x")[1]
            + "*"
            + str(self.__device["resolution"]).split("x")[0],
            "dpi": self.__device["dpi"],
            "update_version_code": application["update_version_code"],
            "_rticket": round(time.time() * 1000),
            "app_type": "normal",
            "sys_region": self.__device["sys_region"],
            "timezone_name": self.__device["timezone_name"],
            "app_language": self.__device["app_language"],
            "ac2": "wifi",
            "uoo": "0",
            "op_region": self.__device["op_region"],
            "timezone_offset": self.__device["offset"],
            "build_number": application["build_number"],
            "locale": self.__device["locale"],
            "region": self.__device["region"],
            "ts": int(time.time()),
            "cdid": self.__device["cdid"],
            "cpu_support64": "true",
            "host_abi": "armeabi-v7a",
        }

        return urlencode(__base_params)

    def __payload(self):

        payload = {
            "magic_tag": "ss_app_log",
            "header": {
                "display_name": "TikTok",
                "update_version_code": application["update_version_code"],
                "manifest_version_code": application["manifest_version_code"],
                "app_version_minor": "",
                "aid": application["aid"],
                "channel": "googleplay",
                "package": "com.zhiliaoapp.musically",
                "app_version": application["app_version"],
                "version_code": application["version_code"],
                "sdk_version": "2.12.1-rc.17",
                "sdk_target_version": 29,
                "git_hash": application["git_hash"],
                "os": "Android",
                "os_version": str(self.__device["os"]),
                "os_api": self.__device["os_api"],
                "device_model": self.__device["device_model"],
                "device_brand": self.__device["device_brand"],
                "device_manufacturer": self.__device["device_brand"],
                "cpu_abi": "armeabi-v7a",
                "release_build": application["release_build"],
                "density_dpi": self.__device["dpi"],
                "display_density": self.__device["display_density"],
                "resolution": self.__device["resolution"],
                "language": self.__device["language"],
                "timezone": self.__device["timezone"],
                "access": "wifi",
                "not_request_sender": 0,
                "rom": self.__device["rom"],
                "rom_version": self.__device["rom_version"],
                "cdid": self.__device["cdid"],
                "sig_hash": application["sig_hash"],
                "gaid_limited": 0,
                "google_aid": self.__device["google_aid"],
                "openudid": self.__device["openudid"],
                "clientudid": self.__device["clientudid"],
                "region": self.__device["region"],
                "tz_name": f"{self.__device['timezone_name'].split('/')[0]}/{self.__device['timezone_name'].split('/')[1]}",
                "tz_offset": self.__device["offset"],
                "req_id": self.__device["req_id"],
                "custom": {
                    "is_kids_mode": 0,
                    "filter_warn": 0,
                    "web_ua": f"Dalvik/2.1.0 (Linux; U; Android {self.__device['os']}; {self.__device['device_model']} Build/{self.__device['build']})",
                    "user_period": 0,
                    "user_mode": -1,
                },
                "apk_first_install_time": self.__device["install_time"],
                "is_system_app": 0,
                "sdk_flavor": "global",
            },
            "_gen_time": round(time.time() * 1000),
        }
        return payload

    @staticmethod
    def __tt_encryption(data: dict) -> str:
        ttencrypt = TTEncrypt()
        data_formated = json.dumps(data).replace(" ", "")
        return ttencrypt.encrypt(data_formated)

    def register_device(self):
        params = self.__params()
        payload = self.__payload()

        r = requests.post(
            url=("https://" + self.__host + "/service/2/device_register/?" + params),
            headers=self.__headers(params),
            data=bytes.fromhex(self.__tt_encryption(payload)),
        )

        if r.json()["device_id"] == 0 or r.json()["device_id"] == "0":
            self.register_device()

        return r.json()["device_id"], r.json()["install_id"]


class Xlog:
    def __init__(self, __device_id):
        self.__device_id = __device_id

    def bypass(self):
        params = urlencode(
            {
                "os": "0",
                "ver": "0.6.11.29.19-MT",
                "m": "2",
                "app_ver": "19.1.3",
                "region": "en_US",
                "aid": "1233",
                "did": self.__device_id,
            }
        )
        sig = Xgorgon().calculate(params, None, None)

        headers = {
            "accept-encoding": "gzip",
            "cookie": "sessionid=",
            "x-ss-req-ticket": str("".join(str(time.time()).split(".")))[:13],
            "x-tt-dm-status": "login=0;ct=0",
            "x-gorgon": sig["x-gorgon"],
            "x-khronos": str(sig["x-khronos"]),
            "host": "xlog-va.tiktokv.com",
            "connection": "Keep-Alive",
            "user-agent": "okhttp/3.10.0.1",
        }

        url = "https://xlog-va.tiktokv.com/v2/s?" + params

        response = requests.get(url, headers=headers)
        