# This project is discontinued!
For a simpler solution to generate TikTok stream keys check my other project [here](https://github.com/Loukious/StreamLabsTikTokStreamKeyGenerator)


# TikTok Live Stream Key Generator for OBS Studio

## Description
This Python script is a valuable tool for content creators looking to broadcast on TikTok's live streaming platform using OBS Studio, an alternative to TikTok LIVE Studio. The script's standout feature is generating a stream key, a capability typically restricted and highly sought after. This stream key enables users to stream via OBS Studio, offering more control and flexibility over their live broadcasts. Additionally, the script provides the base stream URL and a shareable URL for the stream.

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/loukious)


## Features
- Retrieve the base stream URL.
- Generate a TikTok stream key.
- Obtain a shareable URL for the TikTok live stream.
- Support for specifying different topics including games, music, and more.
- Spoofing support for users without TikTok LIVE Studio access (Currently broken don't use it).
- Generate a fake device for spoofing.
- Option to enable replay generation.
- Option to close the room when the stream ends.
- Option to choose region priority.
- Option to mark the stream as mature content.
- Button to end the stream.
- Option to use custom thumbnail.

## Requirements
- Python 3.6+
- Google Chrome browser
- Game tag ID
- Logged into TikTok LIVE studio at least once
- Have TikTok LIVE studio access or Live access (use spoofing if you don't have access to TikTok LIVE studio)

## Installation
Either download and use the provided exe from [here](https://github.com/Loukious/TikTokStreamKeyGenerator/releases/latest) or follow the steps below to run the script.
Ensure you have Python and PIP working.
In the command line, install the required packages using the following command (run the command in the same directory as the script):
```bash
pip install -r requirements.txt
```
or if pip is not working, try:
```bash
python -m pip install -r requirements.txt
```

## Usage
Simply run the script to open the GUI.

### Command Format
```bash
python TikTokStreamKeyGenerator.py
```

Press the login button to login to TikTok. After logging in, you can enter the game tag ID, stream title, and other options. Press the go live button to generate the stream key.

## Output

The script will output:
- **Base stream URL:** The URL needed to connect to the TikTok live stream.
- **Stream key for OBS Studio integration:** Stream key that that you can use in OBS Studio to stream to TikTok.
- **Shareable URL for the live stream:** A URL that can be shared for others to view the live stream.

## FAQ
### I'm getting a `Please login first` error. What should I do?
Try a different server from the one you're using.
### I'm getting a `Maximum number of attempts reached. Try again later.` error. What should I do?
This error sometimes occurs when TikTok detects selenium. You can use this [extension](https://chromewebstore.google.com/detail/export-cookie-json-file-f/nmckokihipjgplolmcmjakknndddifde) to export your cookies and import them into the script.
- Start by installing the above extension in your browser.
- Log into TikTok in the browser (if not already logged in), then export the cookies using the extension (while being on TikTok's website). 
- After that, place the file in the same directory as the script and rename it to `cookies.json` then start the app.
### Do I need live access to use this script?
Yes, you need to have access to TikTok LIVE to use this script.
