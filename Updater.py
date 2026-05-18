import requests
from packaging import version

from _version import __version__


class VersionChecker:
    REPO = "Loukious/TikTokStreamKeyGenerator"

    @classmethod
    def check_update(cls):
        try:
            response = requests.get(
                f"https://api.github.com/repos/{cls.REPO}/releases/latest",
                timeout=5,
            )
            response.raise_for_status()
            release = response.json()
            latest = release["tag_name"].lstrip("v")

            if version.parse(latest) > version.parse(__version__):
                return {
                    "current": __version__,
                    "latest": latest,
                    "url": release["html_url"],
                    "notes": release.get("body", ""),
                }
        except Exception:
            return None

        return None
