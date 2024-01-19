import requests
import json
import sys

class Stream:
    def __init__(self, sid_guard_cookie, title, game_tag_id, gen_replay=False, close_room_when_close_stream=True):
        self.streamInfo = self.createStream(sid_guard_cookie, title, game_tag_id, gen_replay, close_room_when_close_stream)
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


    def createStream(self, sid_guard_cookie, title, game_tag_id, gen_replay=False, close_room_when_close_stream=True):
        url = "https://webcast16-normal-c-useast2a.tiktokv.com/webcast/room/create/"
        params = {
            "aid": "8311" # Not sure what this is 
        }
        data = {
            "title": title, # Title of stream
            "hashtag_id": "5", # Gaming?
            "game_tag_id": game_tag_id, # Game ID find more at https://webcast16-normal-c-useast2a.tiktokv.com/webcast/room/hashtag/list/
            "gen_replay": gen_replay, # To generate replay
            "close_room_when_close_stream": close_room_when_close_stream, # To close room when stream is closed
            "live_studio": "1" # To mark stream as gaming stream
        }
        headers = {
            "cookie": "sid_guard=" + sid_guard_cookie, # Your cookie
            "user-agent": ""
        }
        with requests.session() as s:
            info = s.post(url, params=params, data=data, headers=headers).json()
        return info


if len(sys.argv) < 4:
    print("Usage: python TikTokStreamKeyGenerator.py <sid_guard_cookie> <title> <game_tag_id> [gen_replay] [close_room_when_close_stream]")
    sys.exit(1)

sid_guard_cookie = sys.argv[1]
title = sys.argv[2]
game_tag_id = sys.argv[3]
gen_replay = sys.argv[4].lower() == 'true' if len(sys.argv) > 4 else False
close_room_when_close_stream = sys.argv[5].lower() == 'true' if len(sys.argv) > 5 else True

s = Stream(sid_guard_cookie, title, game_tag_id, gen_replay, close_room_when_close_stream)

if s.created:
    print(s.baseStreamUrl)
    print(s.streamKey)
    print(s.streamShareUrl)