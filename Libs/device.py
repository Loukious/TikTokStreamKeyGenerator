import os
import random
import time, base64, datetime, pytz, uuid, binascii

from .constants import *


class Device:
    def __init__(self):
        pass

    @staticmethod
    def __setup_timezone(country_code: str) -> dict:
        timezone_name = random.choice(pytz.country_timezones[country_code])
        timezone = round(
            int(
                datetime.datetime.now(pytz.timezone(timezone_name)).utcoffset().seconds
                / 3600
            )
        )
        offset = round(
            datetime.datetime.now(pytz.timezone(timezone_name))
            .utcoffset()
            .total_seconds()
        )
        return {
            "timezone_name": timezone_name,
            "timezone": timezone,
            "offset": offset,
        }

    @staticmethod
    def __setup_locale(country_code: str) -> str:
        try:
            search_country = [
                country for country in locales if country_code in country.keys()
            ]
            return search_country[0][country_code]
        except Exception as e:
            raise ValueError(e)

    @staticmethod
    def __set_gmt(timezone: int) -> str:
        if 0 < timezone < 10:
            result = "GMT+0{}:00".format(str(timezone))
        if 0 > timezone > -10:
            result = "GMT-0{}:00".format(str(timezone))
        if 0 < timezone and timezone >= 10:
            result = "GMT+{}:00".format(str(timezone))
        if timezone < 0 and timezone <= -10:
            result = "GMT+{}:00".format(str(timezone))
        return result

    @staticmethod
    def __guuid() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def __openudid() -> str:
        return binascii.hexlify(os.urandom(8)).decode()

    @staticmethod
    def __detect_api_level(os_version: float) -> int:
        if os_version == 7.0:
            return 24
        if os_version == 8.0:
            return 26
        if os_version == 9.0:
            return 28
        if os_version == 10.0:
            return 29
        if os_version == 11.0:
            return 30

    @staticmethod
    def __security_path() -> str:
        paths = []
        for i in range(2):
            random_bytes = os.urandom(16)
            encoded_path = base64.urlsafe_b64encode(random_bytes).decode()
            paths.append(encoded_path)
        return f"/data/app/~~{paths[0]}/com.zhiliaoapp.musically-{paths[1]}/base.apk"

    def create_device(self, country_code: str = "us"):
        simple_device = random.choice(devices)

        timezone_params = self.__setup_timezone(country_code)
        locales_params = self.__setup_locale(country_code)
        gmt = self.__set_gmt(timezone_params["timezone"])

        build = random.choice(simple_device["build"])
        rom = random.choice(simple_device["rom"])
        core = random.choice(simple_device["core"])
        model = random.choice(simple_device["model"])
        product_info = random.choice(simple_device["device"])
        board = random.choice(simple_device["board"])

        device_i = product_info["device"]
        product = product_info["product"]

        device = {
            "device_brand": simple_device["brand"],
            "device_model": model,
            "google_aid": self.__guuid(),
            "cdid": self.__guuid(),
            "clientudid": self.__guuid(),
            "req_id": self.__guuid(),
            "build": build,
            "rom": rom,
            "rom_version": build + "." + rom,
            "resolution": simple_device["resolution"],
            "timezone_name": timezone_params["timezone_name"],
            "timezone": timezone_params["timezone"],
            "offset": timezone_params["offset"],
            "locale": locales_params,
            "os": simple_device["os"],
            "os_api": self.__detect_api_level(simple_device["os"]),
            "openudid": self.__openudid(),
            "display_density": simple_device["display_density"],
            "dpi": simple_device["dpi"],
            "device": device_i,
            "product": product,
            "install_time": int(round(time.time() * 1000))
            - random.randint(5000, 30000),
            "region": country_code.upper(),
            "language": "en" if country_code == "us" else country_code,
            "app_language": "en" if country_code == "us" else country_code,
            "op_region": country_code.upper(),
            "sys_region": country_code.upper(),
            "core": core,
            "board": board,
            "gmt": gmt,
            "ut": random.randint(100, 500),
            "cba": hex(random.randint(1000000000, 5900000000)),
            "ts": random.randint(-1414524480, -1014524480),
            "uid": random.randrange(10000, 10550, 50),
            "dp": random.randint(100000000, 999999999),
            "hc": f"0016{random.randint(500000, 999999)}",
            "bas": random.randint(10, 100),
            "bat": random.randrange(3500, 4900, 500),
            "path": self.__security_path(),
            "dbg": random.randint(-100, 0),
            "token_cache": base64.urlsafe_b64encode(os.urandom(108))
            .decode()
            .replace("=", "_"),
        }
        return device
