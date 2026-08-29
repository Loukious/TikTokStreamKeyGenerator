# TikTok Live Stream Key Generator for OBS Studio

This project creates a TikTok LIVE room and gives OBS an RTMP target through a local FFmpeg proxy. OBS does not stream directly to TikTok; it streams to the local proxy, and the proxy forwards the stream with the metadata TikTok expects.

For most users, [Loukious/StreamLabsTikTokStreamKeyGenerator](https://github.com/Loukious/StreamLabsTikTokStreamKeyGenerator) is still the preferred option. It has a smaller architecture, fewer moving parts, and therefore less that can go wrong. Use this project if you specifically need the newer local FFmpeg proxy flow, SEI injection path, RapidAPI signing integration, or the extra GUI controls here.

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/loukious)

## What It Does

- Creates a TikTok LIVE room.
- Retrieves the stream server, stream key, and share URL.
- Supports OBS Studio by exposing a local RTMP server/key pair.
- Runs a local FFmpeg RTMP proxy between OBS and TikTok.
- Adds the LIVE Studio-style stream metadata needed by the proxy path.
- Supports game/topic tags, replay settings, mature content, thumbnails, region priority, and ending the room from the app.
- Uses RapidAPI for request signing and stream frame signing.

## Architecture

The supported streaming path is:

1. The app creates a TikTok LIVE room and receives the real TikTok push URL/key.
2. The app starts a local FFmpeg RTMP proxy.
3. OBS connects to the local RTMP address shown by the app, usually something like `rtmp://127.0.0.1:<port>/...`.
4. The proxy receives the OBS stream, adds the stream metadata path TikTok expects, and forwards it to TikTok.

The real TikTok URL/key is not meant to be used directly in OBS. In current testing, TikTok closes direct OBS connections immediately, and using the real TikTok URL/key without the LIVE Studio-style stream metadata can lead to a LIVE visibility restriction for integrity/authenticity.

The local proxy exists because TikTok LIVE Studio sends extra stream-side metadata while pushing video. OBS does not send that metadata by itself. The proxy lets OBS stay simple while the app handles the TikTok-specific stream wrapping before forwarding.

## RapidAPI Signing

This app requires a signer API key for TikTok request headers and stream frame signing. The app does not explain or expose the signing algorithms; it calls the hosted signer API and uses the returned values.

You need a RapidAPI key from:

[TikTok LIVE Studio API Signer on RapidAPI](https://rapidapi.com/Loukious/api/tiktok-live-studio-api-signer1)

After subscribing:

1. Open the app.
2. Paste your RapidAPI key into the **RapidAPI Key** field.
3. Save/apply it.
4. Start the stream normally.

Without a valid RapidAPI key, streaming is expected to fail or receive a LIVE visibility restriction such as an integrity/authenticity violation. Treat the RapidAPI key as required, not optional.

## Requirements

- Python 3.10+ recommended.
- FFmpeg available on `PATH`.
- OBS Studio.
- TikTok LIVE access.
- TikTok LIVE Studio access or an account that has already been enabled for LIVE Studio.
- A valid RapidAPI key for this app's signer API.

## Installation

Download the latest release from:

https://github.com/Loukious/TikTokStreamKeyGenerator/releases/latest

Or run from source:

```bash
pip install -r requirements.txt
```

If `pip` is not available:

```bash
python -m pip install -r requirements.txt
```

## Usage

Run the GUI:

```bash
python TiktokStreamKeyGenerator.py
```

Then:

1. Log in to TikTok.
2. Enter your stream title and game/topic options.
3. Paste your RapidAPI key if it is not already saved.
4. Click **Go Live**.
5. Copy the local server/key shown by the app into OBS.

OBS should use the local RTMP server/key shown by the app, not the real TikTok URL/key.

## Logging In With Exported Cookies

If browser login is unavailable or keeps failing, you can skip it by importing cookies from a browser where you are already logged in to TikTok:

1. Install the [Export cookie JSON file for Puppeteer](https://chromewebstore.google.com/detail/export-cookie-json-file-f/nmckokihipjgplolmcmjakknndddifde) extension in Chrome.
2. Log in to TikTok in Chrome and stay on a `tiktok.com` page.
3. Click the extension icon and export the cookies. It downloads a JSON file containing the session for the site you are on.
4. In the app, point the **Cookies file** field at the downloaded JSON file (type or paste the path, or edit `cookies_path` in the config), then use **Refresh Account Info**.

The exported file is a JSON array of `{name, value, domain, ...}` cookie objects, which is the format the app reads directly.

Notes:

- Make sure you export while logged in with the account you intend to stream from.
- Cookie files are live account credentials. Do not share them or commit them to git.
- Sessions expire; if the app stops authenticating, log in again in the browser and export a fresh file.

## Dual Layout (Portrait + Landscape)

Check **Dual Layout (Portrait + Landscape)** in the Options before clicking **Go Live** to create a `multi_stream_scene=1` room with two canvases. The app then starts two signed local RTMP listeners:

- **Stream URL / Stream Key** (labeled *Landscape* in dual mode) — the existing endpoint, by default `rtmp://127.0.0.1:19350/live/obs`, forwards to the room's **landscape** canvas (`multi_stream_url`). Existing OBS setups keep working unchanged.
- **Portrait Stream URL / Stream Key** — a second endpoint, by default `rtmp://127.0.0.1:19351/live/portrait`, forwards to the room's **portrait/vertical** canvas (the main `stream_url`).

Feed the portrait endpoint from a second encoder output: an OBS multi-RTMP output plugin, a second OBS instance with a vertical canvas, or an `ffmpeg` push.

Notes:

- The account must be allowed dual layout. If TikTok does not return a second push URL, the app ends the freshly created room and tells you to retry without the checkbox.
- Resuming an existing room only stays dual when that room has a `multi_stream_url`; otherwise the app continues with the main canvas only.
- If either proxy process dies, forwarding is halted on both endpoints (signed metadata can no longer be trusted for the room).
- Both endpoints sign with the same SEI parameters as the single-stream proxy.

## Output

The app can show:

- **Server URL:** The RTMP server OBS should connect to.
- **Stream key:** The OBS stream key.
- **Share URL:** A public link to the TikTok live room.

The shown server/key are local proxy values. The app keeps the real TikTok push URL internal so OBS only talks to the local proxy.

## FAQ

### Why is the StreamLabs project preferred?

It has a smaller flow and fewer dependencies. This project has more advanced features, but that also means more components: login, room creation, request signing, FFmpeg, local RTMP proxying, and stream metadata injection.

### Why do I need FFmpeg?

FFmpeg is used as the local RTMP receiver/forwarder. OBS streams to FFmpeg locally, and FFmpeg forwards the stream after the app adds the TikTok-specific stream metadata path. Direct OBS-to-TikTok streaming is not the supported path here.

### Why do I need RapidAPI?

TikTok LIVE Studio requests and stream metadata require signed values. The app gets those signed values from the RapidAPI signer service. Without them, the stream can be restricted for integrity/authenticity.

### Do I need TikTok LIVE access?

Yes. The app cannot give LIVE access to accounts that do not already have permission to go live.

### I get a login error. What should I do?

Try logging in again, restarting the app, or using another available TikTok server/region option. If browser login is blocked, you can import cookies exported from your browser instead — see [Logging In With Exported Cookies](#logging-in-with-exported-cookies).
