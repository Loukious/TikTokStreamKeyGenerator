# TikTok Live Stream Key Generator for OBS Studio

## Description
This Python script is a valuable tool for content creators looking to broadcast on TikTok's live streaming platform using OBS Studio, an alternative to TikTok LIVE Studio. The script's standout feature is generating a stream key, a capability typically restricted and highly sought after. This stream key enables users to stream via OBS Studio, offering more control and flexibility over their live broadcasts. Additionally, the script provides the base stream URL and a shareable URL for the stream.

## Features
- Retrieve the base stream URL.
- Generate a TikTok stream key.
- Obtain a shareable URL for the TikTok live stream.
- Support for specifying different games by their game tag IDs.

## Requirements
- Python 3.6+
- `requests` library
- TikTok `sid_guard` cookie
- Game tag ID
- Logged into TikTok LIVE studio at least once
- Have TikTok LIVE studio access

## Obtaining the `sid_guard` cookie
To use this script, you need the `sid_guard` cookie from TikTok. This can be obtained through:

### Using Chrome Developer Tools
1. Open Chrome and navigate to TikTok's website.
2. Right-click anywhere on the page and select "Inspect" to open the Developer Tools.
3. Navigate to the "Application" tab.
4. Under "Cookies" on the left, find the TikTok domain and locate the `sid_guard` cookie. Copy its value.

### Using EditThisCookie Extension
1. Install [EditThisCookie](https://chromewebstore.google.com/detail/editthiscookie/fngmhnnpilhplaeedifhccceomclgfbg) for Chrome.
2. Visit TikTok's website and click the EditThisCookie extension icon.
3. Locate and copy the value of the `sid_guard` cookie.

## Finding Game Tag IDs
1. Download and install this extension: [JSON Formatter](https://chromewebstore.google.com/detail/json-formatter/bcjindcccaagfpapjjmafapmmgkkhgoa) (optional but recommended).
2. Visit this url to find [TikTok Live API Game Tag List](https://webcast16-normal-c-useast2a.tiktokv.com/webcast/room/hashtag/list/).
3. Use the id from the list to specify the game tag ID.


## Installation
Ensure you have Python and the `requests` library installed.

```bash
pip install requests
```

## Usage
Run the script with the necessary parameters from the command line.

### Command Format
```bash
python TikTokStreamKeyGenerator.py <sid_guard> <title> <game_tag_id> [gen_replay] [close_room_when_close_stream]
```

- `sid_guard_cookie`: Your TikTok SID guard cookie.
- `title`: Title of your stream.
- `game_tag_id`: Game tag ID from [TikTok Live API Game Tag List](https://webcast16-normal-c-useast2a.tiktokv.com/webcast/room/hashtag/list/).
- `gen_replay` (optional): `true` to enable replay generation.
- `close_room_when_close_stream` (optional): `true` to close the room when the stream ends.

### Example

```bash
python TikTokStreamKeyGenerator.py "your_sid_guard_cookie" "My Stream Title" "12345" true false
```
## Output

The script will output:
- **Base stream URL:** The URL needed to connect to the TikTok live stream.
- **Stream key for OBS Studio integration:** Stream key that that you can use in OBS Studio to stream to TikTok.
- **Shareable URL for the live stream:** A URL that can be shared for others to view the live stream.

## FAQ
### I'm getting a "Please login first" error. What should I do?
Swap the url inside TikTokStreamKeyGenerator.py at the line 21.