import re, json, os, sys, logging, urllib3, random, string, threading, time, base64, uuid, datetime, time
import certifi
# from requests_toolbelt.adapters.ssl import SSLAdapter # Lưu ý: SSLAdapter này được import từ requests_toolbelt
import rsa
import shutil
from pyfiglet import Figlet 
import requests
from pystyle import Colors, Colorate, Center
import requests, json, time, base64, random, rsa, certifi, traceback
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.ssl_ import create_urllib3_context
from datetime import datetime
from time import sleep
import requests, json, time, base64, random, rsa, certifi, traceback
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.ssl_ import create_urllib3_context
from datetime import datetime

def gradient_3(text):
    def rgb_to_ansi(r, g, b):
        return f"\033[38;2;{r};{g};{b}m"

    start = (0, 255, 0)   # xanh lá
    end   = (0, 128, 255) # xanh biển

    result = ""
    for i, char in enumerate(text):
        t = i / (len(text) - 1 if len(text) > 1 else 1)
        r = int(start[0] + (end[0] - start[0]) * t)
        g = int(start[1] + (end[1] - start[1]) * t)
        b = int(start[2] + (end[2] - start[2]) * t)
        result += rgb_to_ansi(r, g, b) + char
    return result + "\033[0m"
    
def gradient_tutu(text):
    def rgb_to_ansi(r, g, b):
        return f"\033[38;2;{r};{g};{b}m"

    start_color = (0, 255, 255)    # Cyan
    mid_color   = (255, 0, 255)    # Magenta
    end_color   = (255, 255, 0)    # Yellow

    steps = len(text)
    result = ""

    for i, char in enumerate(text):
        t = i / (steps - 1 if steps > 1 else 1)

        if t < 0.5:
            t2 = t / 0.5
            r = int(start_color[0] + (mid_color[0] - start_color[0]) * t2)
            g = int(start_color[1] + (mid_color[1] - start_color[1]) * t2)
            b = int(start_color[2] + (mid_color[2] - start_color[2]) * t2)
        else:
            t2 = (t - 0.5) / 0.5
            r = int(mid_color[0] + (end_color[0] - mid_color[0]) * t2)
            g = int(mid_color[1] + (end_color[1] - mid_color[1]) * t2)
            b = int(mid_color[2] + (end_color[2] - mid_color[2]) * t2)

        result += rgb_to_ansi(r, g, b) + char

    return result + "\033[0m"
    
def inp(text, colors=None):
    if not colors:
        colors = [129, 93, 57, 63, 69, 75, 81, 87, 93, 99, 105, 111, 117, 123]
    result = ""
    for i, c in enumerate(text):
        color = colors[i % len(colors)]
        result += f"\033[38;5;{color}m{c}"
    return result + "\033[0m"
    
def gradient_2(text):
    def rgb_to_ansi(r, g, b):
        return f"\033[38;2;{r};{g};{b}m"

    start_color = (255, 87, 34)    
    mid_color   = (255, 20, 147)    
    end_color   = (255, 255, 0)     
    steps = len(text)
    result = ""

    for i, char in enumerate(text):
        t = i / (steps - 1 if steps > 1 else 1)

        if t < 0.5:
            t2 = t / 0.5
            r = int(start_color[0] + (mid_color[0] - start_color[0]) * t2)
            g = int(start_color[1] + (mid_color[1] - start_color[1]) * t2)
            b = int(start_color[2] + (mid_color[2] - start_color[2]) * t2)
        else:
            t2 = (t - 0.5) / 0.5
            r = int(mid_color[0] + (end_color[0] - mid_color[0]) * t2)
            g = int(mid_color[1] + (end_color[1] - mid_color[1]) * t2)
            b = int(mid_color[2] + (end_color[2] - mid_color[2]) * t2)

        result += rgb_to_ansi(r, g, b) + char

    return result + "\033[0m"
    
def gradient_1(text):
    def rgb_to_ansi(r, g, b):
        return f"\033[38;2;{r};{g};{b}m"
    
    colors = [
        (0, 255, 255),      # Cyan neon sáng
        (0, 200, 255),      # Xanh neon
        (0, 150, 255),      # Xanh dương neon
        (100, 100, 255),    # Xanh tím nhạt
        (150, 50, 255),     # Tím neon
        (200, 0, 255),      # Tím sáng
        (255, 0, 200),      # Hồng tím
    ]
    
    result = ""
    length = len(text)
    
    for i, char in enumerate(text):
        color_index = (i / max(1, length - 1)) * (len(colors) - 1)
        idx1 = int(color_index)
        idx2 = min(idx1 + 1, len(colors) - 1)
        ratio = color_index - idx1
        
        r = int(colors[idx1][0] + (colors[idx2][0] - colors[idx1][0]) * ratio)
        g = int(colors[idx1][1] + (colors[idx2][1] - colors[idx1][1]) * ratio)
        b = int(colors[idx1][2] + (colors[idx2][2] - colors[idx1][2]) * ratio)
        
        result += rgb_to_ansi(r, g, b) + char
    
    return result + "\033[0m"
    
def gradient(text, start_color=(255, 0, 255), end_color=(0, 255, 255)):
    result = ""
    length = len(text)
    for i, char in enumerate(text):
        r = int(start_color[0] + (end_color[0] - start_color[0]) * i / (length - 1))
        g = int(start_color[1] + (end_color[1] - start_color[1]) * i / (length - 1))
        b = int(start_color[2] + (end_color[2] - start_color[2]) * i / (length - 1))
        result += f"\033[38;2;{r};{g};{b}m{char}"
    result += "\033[0m"
    return result


def print_rtv(text, end='\n'):
    output = gradient_tutu(text)
    print(output + reset, end=end, flush=True)

def input_rtv(prompt):
    output = gradient_tutu(prompt)
    return input(output + reset)
trang='\033[39m'
reset='\033[0m'
def print_job_success(stt, job_type, target, giajob, xu):
    # Sửa hàm chỉ nhận 5 tham số
    stt_text = f"{trang}{stt}{trang}"
    time_text = gradient_1(datetime.now().strftime("%H:%M:%S"))  # Thêm thời gian
    type_text = f"{trang}{job_type.upper()}{trang}"
    id_text = gradient_1(target) 
    msg_text = f"{trang}+{giajob}Đ{trang}" 
    xu_text = f"{trang}{str(format(int(str(xu).replace(',', '')), ','))}{trang}"
    
    result = f"{trang}[{stt_text}{trang}]{trang}[{type_text}{trang}]{trang}[{time_text}{trang}]{trang}[{msg_text}{trang}]{trang}[{id_text}{trang}]{trang}[{xu_text}{trang}]{reset}"
    
    console.print(result, flush=True)
    
# ----------------- DEBUG LOGGER -----------------
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
import os



# ====== LOGO TLTOOL INSERT ======
def thanhngang(n=60):
    print("─" * n)

def gradient_tutu(text):
    return text


def banner():
    RESET = "\033[0m"
    BOLD  = "\033[1m"

    C1 = "\033[38;5;51m"
    C2 = "\033[38;5;75m"
    C3 = "\033[38;5;99m"
    C4 = "\033[38;5;129m"
    C5 = "\033[38;5;196m"

    logo = f"""{BOLD}
{C1}████████╗██╗          ████████╗ ██████╗  ██████╗ ██╗
{C2}╚══██╔══╝██║          ╚══██╔══╝██╔═══██╗██╔═══██╗██║
{C3}   ██║   ██║             ██║   ██║   ██║██║   ██║██║
{C4}   ██║   ██║             ██║   ██║   ██║██║   ██║██║
{C5}   ██║   ███████╗        ██║   ╚██████╔╝╚██████╔╝███████╗
{C5}   ╚═╝   ╚══════╝        ╚═╝    ╚═════╝  ╚═════╝ ╚══════╝
{RESET}
"""
    print(logo)
    thanhngang(65)
    print(gradient_tutu("[</>] CHUC AE CHẠY TOOL KIẾM NHIỀU"))
    print(gradient_tutu("[</>] BOX ZALO : https://zalo.me/g/buxmoo796"))
    print(gradient_tutu("[</>] ZALO CÁ NHÂN : 0352816362"))
    print(gradient_tutu("[</>] WEBSITE FB CỔ SCAN : https://betammo.site/client/home"))
    thanhngang(65)


banner()
# ====== END LOGO INSERT ======

console = Console()


def banner():
    os.system("cls" if os.name == "nt" else "clear")

    banner_text = r"""
╭━━━┳━━━┳━━━┳━━━┳━━━━╮
┃╭━╮┃╭━╮┃╭━╮┣╮╭╮┣━━╮━┃
┃╰━╯┃┃╱┃┃╰━╯┃┃┃┃┃╱╭╯╭╯
┃╭━━┫╰━╯┃╭━━╯┃┃┃┃╭╯╭╯
┃┃╱╱┃╭━╮┃┃╱╱╭╯╰╯┣╯━╰━╮
╰╯╱╱╰╯╱╰┻╯╱╱╰━━━┻━━━━╯
"""

    # Danh sách 7 màu cầu vồng (rich hỗ trợ #hex hoặc tên màu)
    rainbow_colors = ["red", "dark_orange3", "yellow", "green", "cyan", "blue", "magenta"]

    # Tạo Text với 7 màu luân phiên từng ký tự
    rainbow_text = Text()
    for i, ch in enumerate(banner_text):
        color = rainbow_colors[i % len(rainbow_colors)]
        rainbow_text.append(ch, style=color)

    console.print(Panel(rainbow_text, border_style="bold magenta", expand=False))

    info = [
        ("YouTube", "https://www.youtube.com/@phuocan.8899"),
        ("TikTok", "https://www.tiktok.com/@_tinhyeu_k"),
        ("Admin", "PhuocAnCoder"),
    ]

    for label, value in info:
        text = Text()
        text.append(f"{label:<10}: ", style="bold cyan")
        text.append(value, style="bold yellow")
        console.print(text)

    console.print()  # dòng trống


# --- SSL Adapter chuẩn TLS ---


import certifi
from requests_toolbelt.adapters.ssl import SSLAdapter
import rsa

class JsonCacheSession:
    def __init__(self, nameSession='PAPXKKTOOL'):
        super().__setattr__('_data', {})  # lưu dữ liệu dict
        super().__setattr__('nameSession', nameSession)
        os.makedirs("cache", exist_ok=True)

        # ✅ Nếu file session tồn tại thì load lại
        session_file = f"cache/{nameSession}.PAP"
        if os.path.isfile(session_file):
            self._load_cache()
        else:
            self._save_cache()  # tạo file mới nếu chưa có

    def __setattr__(self, name, value):
        if name.startswith('_') or name == 'nameSession':
            super().__setattr__(name, value)
        else:
            # Nếu value là dict hoặc list, lưu trực tiếp
            self._data[name] = value
            self._save_cache()

    def __getattr__(self, name):
        if name == "getdata":
            # Trả về object getter để đọc dữ liệu
            class Getter:
                def __init__(self, outer):
                    self._outer = outer

                def __getattr__(self, name):
                    outer = self.__dict__['_outer']
                    value = outer._data.get(name)
                    return value  # trả trực tiếp dict/list/string, không decode

            return Getter(self)
        # Trường hợp attr không tồn tại
        return None

    def _save_cache(self):
        path = f"cache/{self.nameSession}.PAP"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[DEBUG] Save error: {e}")

    def _load_cache(self):
        path = f"cache/{self.nameSession}.PAP"
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._data = {}

class MODULE_GOLIKE_FACEBOOK ():
    def _get_T(self, t= None):
            
        ts_bytes = str(int(time.time()) if t is None else int(t)).encode('utf-8')
        for _ in range(3):
            ts_bytes = base64.b64encode(ts_bytes)
        return ts_bytes.decode('utf-8')
    def b64decrypt_3times(self,data: str) -> str:
        for i in range(3):
            data = base64.b64decode(data)
        return data.decode()
    def encode_triple_base64(self,data):
        if isinstance(data, str):
            data = data.encode('utf-8')  # chuyển str → bytes
        b1 = base64.b64encode(data)
        b2 = base64.b64encode(b1)
        b3 = base64.b64encode(b2)
        return b3.decode('utf-8')
    def  __init__(self):

        self.SessionGo = JsonCacheSession("GolikeCavhe")
        self.api = requests.Session()
        if not self.SessionGo.getdata.DATAGO:
            self.SessionGo.DATAGO = {}  # gán trực tiếp vào cache
        self.DATAGO = self.SessionGo.getdata.DATAGO
        req=  requests.Session()
        req.verify=certifi.where()
        try:
            req.mount("https://", SSLAdapter("TLSv1_2"))
        except:
            pass
        req.trust_env = False 
        self.req=req
        
        self.publicKey = ''
        self.privateKey=  ''
        self.cache = {}
    
        self.host= None
    def GetHost (self):
        if self.host:
            return self.host
        else:
            # self.host = 'http://127.0.0.1:5551'
            self.host = self.api.get ('https://raw.githubusercontent.com/dacohacotool/host_kk/refs/heads/main/url_serverkey.txt').text
            return self.host
    def cipher (self, data,public= None, private = None, type= 1):
        if public is None or private is None:
            public_key, private_key = rsa.newkeys(128)
            if public is None:
                public = public_key.save_pkcs1().decode()
            if private is None:
                private = private_key.save_pkcs1().decode()
        if isinstance(data, dict):
            data = json.dumps(data)
        return self.api.post (
            f'{self.GetHost()}/golikeFB/cipher/', json= {
                    'data':data,
                    'type':type, # 1,2,3,4
                    'publickey':public,
                    'privatekey':private
                }
        ).json()
    def get_headers (self):
        return {
                "Accept": "application/json, text/plain, */*",
                #   "Accept-Encoding": "gzip, deflate, br, zstd",
                "Accept-Language": "vi-VN,vi;q=0.9,ja-JP;q=0.8,ja;q=0.7,en-US;q=0.6,en;q=0.5",
                "Content-Type": "application/json;charset=UTF-8",
                # "Host": "api.golike.net",
                "Origin": "https://app.golike.net",
                "sec-ch-ua": "\"Chromium\";v=\"136\", \"Android WebView\";v=\"136\", \"Not.A/Brand\";v=\"99\"",
                "sec-ch-ua-mobile": "?1",
                "sec-ch-ua-platform": "\"Android\"",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                'upgrade-insecure-requests': '1',
                "User-Agent": "Mozilla/5.0 (Linux; Android 10; SC-03L Build/QP1A.190711.020; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/136.0.7103.60 Mobile Safari/537.36",
                "X-Requested-With": "com.golike",
                'authorization':self.author,
                'T': self._get_T()
                }

    def get_account (self):
        try:
            
            get= self.DATAGO.setdefault (self.username, {}).setdefault ('getAccount', {})
            accc = self.req.get(f'https://gateway.golike.net/api/fb-account?limit=200', headers=self.get_headers()).json()
            if 429 == accc.get('code',200):

                return get.get('fb', accc)
            else:
                get['fb'] = accc
            return accc
        except (KeyError, TypeError, AttributeError, requests.exceptions.RequestException, json.JSONDecodeError) as e:
            print(f"Error occurred: {e}")
            return {}
 
    def setupauth(self,authorization):
        def get_username_golike():
            try:
                
                code=self.req.get(f"https://gateway.golike.net/api/users/me", headers = self.get_headers()).json()
#                print (code)
                if 429 == code.get('code',200):
                   
                    cacheu = self.DATAGO.get (authorization)
                    if cacheu :
                        return cacheu["data"]["username"]
                    else:
                        return False
                else:
                    self.DATAGO[authorization] = code

        
                return code['data']['username']
            except (ValueError, TypeError, OSError, KeyError):return False
        self.author = authorization
        
        self.authorization = authorization.replace("Bearer ","")

        self.username = get_username_golike()

        h= self.DATAGO.setdefault (self.username, {}).setdefault ('headers', {
            'client':random.randint(0, 2**32 - 1)

        })
        self.webdata = {
            "client" : h['client'],
            # "verified_at": "2025-08-25 17:08:14",
            "version_app": "1.5.0",
            "web_version": 94,
            "web_version_text": "3.3.5"
        }
        return self.username
    def cau_hinh (self,id):
        account = self.get_account()
    
        for dt in account.get('data',{}).get('data',[]):
            if str(id) ==  dt['fb_id']:
                dataa = {
                    'id': dt['id'],
                    'username': self.username,
                    'counter_rechecking': dt['counter_rechecking'],
                    'user_id': dt['user_id'],
                    'fb_id': dt['fb_id'],
                    'fb_name': dt['fb_name'],
                    'avatar': dt['avatar'],
                    'avatar_url': dt['avatar_url'],
                    'status':1,
                    'counter_jobs_today': dt['counter_jobs_today'],
                    'total_like_page': dt['total_like_page'],
                    'total_follow': dt['total_follow'],
                    'counter_jobs_like_page_today': dt['counter_jobs_like_page_today'],
                    'counter_jobs_follow_today': dt['counter_jobs_follow_today'],
                    'is_banned': dt['is_banned'],
                    'allow_comment': dt['allow_comment'],
                    'location': dt['location'],
                    'is_paid_now': dt['is_paid_now'],
                    'latest_time_complete_jobs': dt['latest_time_complete_jobs'],
                    'description': dt['description'],
                    'verified_at': dt['verified_at'],
                    'created_at': dt['created_at'],
                    'updated_at': dt['updated_at'],
                    'gender': dt['gender'],
                    'age': dt['age'],
                    'birthday': dt['birthday'],
                    'friends': dt['friends'],
                    'public_subscriptions': dt['public_subscriptions'],
                    'jobs_can_work': dt['jobs_can_work'],
                    'has_jobs_rechecking': 0
                }
                self.account = dataa
                return dataa
        else:
            return False
    def get_data_jobs (self):
       
        data={
            "user": {
                **self.account,
                "data": "hooking",
                # "description": "facebook:account:check_live {truncate=false}|2025-05-10 11:31:08",
                "role": "user",
                "version_app": "1.5.0",
                "web_version": 93,
                "web_version_text": "3.3.3"
                }
        }
        data["user"]["role"] = 'user'
        data["user"]["load_job_like_clone"] = True
        # data["user"]["client"] = self.webdata["client"]
        data["user"]["web_version"] = self.webdata["web_version"]
        data["user"]["web_version_text"] = self.webdata["web_version_text"]
        data["user"]["data"] = "hooking"
        data["user"]["version_app"] = self.webdata["version_app"]
        data=  self.cipher (data=json.dumps (data), type= 1)['data']

        return data
    def reload_jobs (self):
        p =self.req.post ("https://api.golike.net/api/job/reload", data = json.dumps({
            "data":self.get_data_jobs()

        }),headers=self.get_headers()).json()
        data=p
        rt = {**data}

        if 'Đã gửi yêu cầu lấy job, vui lòng quay lại sau 10 giây' == data['message']:
            rt['success'] = True
            return rt
        else:
            rt['success'] = False
            return rt
    def get_jobs (self):
        try:
            p =self.req.post ("https://api.golike.net/api/job", data = json.dumps({
                "data":self.get_data_jobs()
            }),headers=self.get_headers()).json()

            giaima= self.cipher (data=p, type= 2)
            data= giaima['data']
            self.privateKey=giaima['private']
            self.publicKey = giaima['public']
            
            rt = {**data}
            if isinstance(data.get('data'),list):
                for dt in data.get('data'):
                    self.cache[dt['object_id']] = dt
                    # comment_text = dt.get ("message",'')
                    # comment_id = dt.get ("comment",{}).get ("id",0)
                rt['success'] = True
                return rt
            else:
                return {
                'success':False,
                'error':'Hết jobs'
            }
        except (ValueError, KeyError):
            return {
                'success':False,
                'error':'Lỗi khi get jobs'
            }
    def hoan_thanh(self,object_id):
        value = self.cache[object_id]
        parsed = self.req.post('https://api.golike.net/api/job/check_job_success', data=json.dumps({
          'auth':self.encode_triple_base64 (self.privateKey),
          'data': self.cipher (data= json.dumps ({**{
                'ads_id': int(value['id']), 'async': True, 'data': None, 'fb_id': str(self.account['fb_id']),
                'message': None, 'object_id': str(object_id), 'token': self.authorization, 'type': str(value['type']),
                'username': str(self.username), 'users_advertising_id': int(value['id']), 'users_fb_account_id': int(self.account['id']),
                'version_app': self.webdata['version_app']
            }, **({'comment_id': value.get('message'), 
                   'comment_text': value.get('comment', {}).get('id')} if value.get('message') or value.get('comment', {}).get('id') else {})}),public= self.publicKey, type= 3)['data']
            }),headers= self.get_headers()).json()

        if parsed.get('success',False) == False or parsed.get ('status',400) != 200:
            return {"success":False,"coin":0,"messenger":parsed.get ('message','')}
        else:
            return {
                "success":True,
                "coin":0,
                "messenger":parsed.get ('message','')
            }
    def bao_loi(self,object_id):
        g_json=  self.req.post ('https://gateway.golike.net/api/report/send',headers= self.get_headers(),data=json.dumps ({
            "description": "Tôi không muốn làm Job này",
            "users_advertising_id": int( self.cache[object_id]['id']),
            "type": "ads",
            "fb_id": str(self.account['fb_id']),
            "error_type": 0,
            "provider": "facebook",
            "comment": None
            })).json()
        if g_json.get('success',False) == False or g_json.get ('status',400) != 200:
            return {'success':False}
        else:
            return {'success':True}


def decode_base64(encoded_str):
    decoded_bytes = base64.b64decode(encoded_str)
    decoded_str = decoded_bytes.decode('utf-8')
    return decoded_str

def encode_to_base64(_data):
    byte_representation = _data.encode('utf-8')
    base64_bytes = base64.b64encode(byte_representation)
    base64_string = base64_bytes.decode('utf-8')
    return base64_string

class Facebook:
    def __init__(self, cookie: str):
        try:
            self.fb_dtsg = ''
            self.jazoest = ''
            self.cookie = cookie
            self.session = requests.Session()
            self.id = self.cookie.split('c_user=')[1].split(';')[0]
            self.headers = {'authority': 'www.facebook.com', 'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9', 'accept-language': 'vi', 'sec-ch-prefers-color-scheme': 'light', 'sec-ch-ua': '"Chromium";v="106", "Google Chrome";v="106", "Not;A=Brand";v="99"', 'sec-ch-ua-mobile': '?0', 'sec-ch-ua-platform': '"Windows"', 'sec-fetch-dest': 'document', 'sec-fetch-mode': 'navigate', 'sec-fetch-site': 'none', 'sec-fetch-user': '?1', 'upgrade-insecure-requests': '1', 'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36', 'viewport-width': '1366', 'Cookie': self.cookie}
            url = self.session.get(f'https://www.facebook.com/{self.id}', headers=self.headers).url
            response = self.session.get(url, headers=self.headers).text
            matches = re.findall(r'\["DTSGInitialData",\[\],\{"token":"(.*?)"\}', response)
            if len(matches) > 0:
                self.fb_dtsg += matches[0]
                self.jazoest += re.findall(r'jazoest=(.*?)\"', response)[0]
        except:
            pass

    def info(self):
        try:
            get = self.session.get('https://www.facebook.com/me', headers=self.headers).url
            url = 'https://www.facebook.com/' + get.split('%2F')[-2] + '/' if 'next=' in get else get
            response = self.session.get(url, headers=self.headers, params={"locale": "vi_VN"})
            data_split = response.text.split('"CurrentUserInitialData",[],{')
            json_data = '{' + data_split[1].split('},')[0] + '}'
            parsed_data = json.loads(json_data)
            id = parsed_data.get('USER_ID', '0')
            name = parsed_data.get('NAME', '')
            if id == '0' and name == '': return 'cookieout'
            elif '828281030927956' in response.text: return '956'
            elif '1501092823525282' in response.text: return '282'
            elif '601051028565049' in response.text: return 'spam'
            else: id, name = parsed_data.get('USER_ID'), parsed_data.get('NAME')
            return {'success': 200, 'id': id, 'name': name}
        except:
            pass
        
    def likepage(self, id: str):
        try:
            data = {'av': self.id,'fb_dtsg': self.fb_dtsg,'jazoest': self.jazoest,'fb_api_caller_class': 'RelayModern','fb_api_req_friendly_name': 'CometProfilePlusLikeMutation','variables': '{"input":{"is_tracking_encrypted":false,"page_id":"'+str(id)+'","source":null,"tracking":null,"actor_id":"'+str(self.id)+'","client_mutation_id":"1"},"scale":1}','server_timestamps': 'true','doc_id': '6716077648448761',}
            response = self.session.post('https://www.facebook.com/api/graphql/',data=data,headers=self.headers)
            if '"subscribe_status":"IS_SUBSCRIBED"' in response.text:
                return True
            else:
                return False
        except:
            pass

    def follow(self, id: str):
        try:
            data = {'av': self.id,'fb_dtsg': self.fb_dtsg,'jazoest': self.jazoest,'fb_api_caller_class': 'RelayModern','fb_api_req_friendly_name': 'CometUserFollowMutation','variables': '{"input":{"attribution_id_v2":"ProfileCometTimelineListViewRoot.react,comet.profile.timeline.list,unexpected,1719765181042,489343,250100865708545,,;SearchCometGlobalSearchDefaultTabRoot.react,comet.search_results.default_tab,unexpected,1719765155735,648442,391724414624676,,;SearchCometGlobalSearchDefaultTabRoot.react,comet.search_results.default_tab,tap_search_bar,1719765153341,865155,391724414624676,,","is_tracking_encrypted":false,"subscribe_location":"PROFILE","subscribee_id":"'+str(id)+'","tracking":null,"actor_id":"'+str(self.id)+'","client_mutation_id":"5"},"scale":1}','server_timestamps': 'true','doc_id': '25581663504782089',}
            response = self.session.post('https://www.facebook.com/api/graphql/',data=data,headers=self.headers)
            if '"subscribe_status":"IS_SUBSCRIBED"' in response.text:
                return True
            else:
                return False
        except:
            pass

    def reaction(self, id: str, type: str):
        try:
            reac = {"LIKE": "1635855486666999","LOVE": "1678524932434102","CARE": "613557422527858","HAHA": "115940658764963","WOW": "478547315650144","SAD": "908563459236466","ANGRY": "444813342392137"}
            idreac = reac.get(type)
            data = {'av': self.id,'fb_dtsg': self.fb_dtsg,'jazoest': self.jazoest,'fb_api_caller_class': 'RelayModern','fb_api_req_friendly_name': 'CometUFIFeedbackReactMutation','variables': fr'{{"input":{{"attribution_id_v2":"CometHomeRoot.react,comet.home,tap_tabbar,1719027162723,322693,4748854339,,","feedback_id":"{encode_to_base64("feedback:"+str(id))}","feedback_reaction_id":"{idreac}","feedback_source":"NEWS_FEED","is_tracking_encrypted":true,"tracking":["AZWUDdylhKB7Q-Esd2HQq9i7j4CmKRfjJP03XBxVNfpztKO0WSnXmh5gtIcplhFxZdk33kQBTHSXLNH-zJaEXFlMxQOu_JG98LVXCvCqk1XLyQqGKuL_dCYK7qSwJmt89TDw1KPpL-BPxB9qLIil1D_4Thuoa4XMgovMVLAXncnXCsoQvAnchMg6ksQOIEX3CqRCqIIKd47O7F7PYR1TkMNbeeSccW83SEUmtuyO5Jc_wiY0ZrrPejfiJeLgtk3snxyTd-JXW1nvjBRjfbLySxmh69u-N_cuDwvqp7A1QwK5pgV49vJlHP63g4do1q6D6kQmTWtBY7iA-beU44knFS7aCLNiq1aGN9Hhg0QTIYJ9rXXEeHbUuAPSK419ieoaj4rb_4lA-Wdaz3oWiWwH0EIzGs0Zj3srHRqfR94oe4PbJ6gz5f64k0kQ2QRWReCO5kpQeiAd1f25oP9yiH_MbpTcfxMr-z83luvUWMF6K0-A-NXEuF5AiCLkWDapNyRwpuGMs8FIdUJmPXF9TGe3wslF5sZRVTKAWRdFMVAsUn-lFT8tVAZVvd4UtScTnmxc1YOArpHD-_Lzt7NDdbuPQWQohqkGVlQVLMoJNZnF_oRLL8je6-ra17lJ8inQPICnw7GP-ne_3A03eT4zA6YsxCC3eIhQK-xyodjfm1j0cMvydXhB89fjTcuz0Uoy0oPyfstl7Sm-AUoGugNch3Mz2jQAXo0E_FX4mbkMYX2WUBW2XSNxssYZYaRXC4FUIrQoVhAJbxU6lomRQIPY8aCS0Ge9iUk8nHq4YZzJgmB7VnFRUd8Oe1sSSiIUWpMNVBONuCIT9Wjipt1lxWEs4KjlHk-SRaEZc_eX4mLwS0RcycI8eXg6kzw2WOlPvGDWalTaMryy6QdJLjoqwidHO21JSbAWPqrBzQAEcoSau_UHC6soSO9UgcBQqdAKBfJbdMhBkmxSwVoxJR_puqsTfuCT6Aa_gFixolGrbgxx5h2-XAARx4SbGplK5kWMw27FpMvgpctU248HpEQ7zGJRTJylE84EWcVHMlVm0pGZb8tlrZSQQme6zxPWbzoQv3xY8CsH4UDu1gBhmWe_wL6KwZJxj3wRrlle54cqhzStoGL5JQwMGaxdwITRusdKgmwwEQJxxH63GvPwqL9oRMvIaHyGfKegOVyG2HMyxmiQmtb5EtaFd6n3JjMCBF74Kcn33TJhQ1yjHoltdO_tKqnj0nPVgRGfN-kdJA7G6HZFvz6j82WfKmzi1lgpUcoZ5T8Fwpx-yyBHV0J4sGF0qR4uBYNcTGkFtbD0tZnUxfy_POfmf8E3phVJrS__XIvnlB5c6yvyGGdYvafQkszlRrTAzDu9pH6TZo1K3Jc1a-wfPWZJ3uBJ_cku-YeTj8piEmR-cMeyWTJR7InVB2IFZx2AoyElAFbMuPVZVp64RgC3ugiyC1nY7HycH2T3POGARB6wP4RFXybScGN4OGwM8e3W2p-Za1BTR09lHRlzeukops0DSBUkhr9GrgMZaw7eAsztGlIXZ_4"],"session_id":"{uuid.uuid4()}","actor_id":"{self.id}","client_mutation_id":"3"}},"useDefaultActor":false,"__relay_internal__pv__CometUFIReactionsEnableShortNamerelayprovider":false}}','server_timestamps': 'true','doc_id': '7047198228715224',}
            self.session.post('https://www.facebook.com/api/graphql/',headers=self.headers, data=data)
        except:
            pass

    def reactioncmt(self, id: str, type: str):
        try:
            reac = {"LIKE": "1635855486666999","LOVE": "1678524932434102","CARE": "613557422527858","HAHA": "115940658764963","WOW": "478547315650144","SAD": "908563459236466","ANGRY": "444813342392137"}
            g_now = datetime.now()
            d = g_now.strftime("%Y-%m-%d %H:%M:%S.%f")
            datetime_object = datetime.strptime(d, "%Y-%m-%d %H:%M:%S.%f")
            timestamp = str(datetime_object.timestamp())
            starttime = timestamp.replace('.', '')
            id_reac = reac.get(type)
            data = {'av': self.id,'fb_dtsg': self.fb_dtsg,'jazoest': self.jazoest,'fb_api_caller_class': 'RelayModern','fb_api_req_friendly_name': 'CometUFIFeedbackReactMutation','variables': '{"input":{"attribution_id_v2":"CometVideoHomeNewPermalinkRoot.react,comet.watch.injection,via_cold_start,1719930662698,975645,2392950137,,","feedback_id":"'+encode_to_base64("feedback:"+str(id))+'","feedback_reaction_id":"'+id_reac+'","feedback_source":"TAHOE","is_tracking_encrypted":true,"tracking":[],"session_id":"'+str(uuid.uuid4())+'","downstream_share_session_id":"'+str(uuid.uuid4())+'","downstream_share_session_origin_uri":"https://fb.watch/t3OatrTuqv/?mibextid=Nif5oz","downstream_share_session_start_time":"'+starttime+'","actor_id":"'+self.id+'","client_mutation_id":"1"},"useDefaultActor":false,"__relay_internal__pv__CometUFIReactionsEnableShortNamerelayprovider":false}', 'server_timestamps': 'true','doc_id': '7616998081714004',}
            self.session.post('https://www.facebook.com/api/graphql/',headers=self.headers, data=data)
        except:
            pass
    
    def share(self, id: str):
        try:
            data = {'av': self.id,'fb_dtsg': self.fb_dtsg,'jazoest': self.jazoest,'fb_api_caller_class': 'RelayModern','fb_api_req_friendly_name': 'ComposerStoryCreateMutation','variables': '{"input":{"composer_entry_point":"share_modal","composer_source_surface":"feed_story","composer_type":"share","idempotence_token":"'+str(uuid.uuid4())+'_FEED","source":"WWW","attachments":[{"link":{"share_scrape_data":"{\\"share_type\\":22,\\"share_params\\":['+id+']}"}}],"reshare_original_post":"RESHARE_ORIGINAL_POST","audience":{"privacy":{"allow":[],"base_state":"EVERYONE","deny":[],"tag_expansion_state":"UNSPECIFIED"}},"is_tracking_encrypted":true,"tracking":["AZWWGipYJ1gf83pZebtJYQQ-iWKc5VZxS4JuOcGWLeB-goMh2k74R1JxqgvUTbDVNs-xTyTpCI4vQw_Y9mFCaX-tIEMg2TfN_GKk-PnqI4xMhaignTkV5113HU-3PLFG27m-EEseUfuGXrNitybNZF1fKNtPcboF6IvxizZa5CUGXNVqLISUtAWXNS9Lq-G2ECnfWPtmKGebm2-YKyfMUH1p8xKNDxOcnMmMJcBBZkUEpjVzqvUTSt52Xyp0NETTPTVW4zHpkByOboAqZj12UuYSsG3GEhafpt91ThFhs7UTtqN7F29UsSW2ikIjTgFPy8cOddclinOtUwaoMaFk2OspLF3J9cwr7wPsZ9CpQxU21mcFHxqpz7vZuGrjWqepKQhWX_ZzmHv0LR8K07ZJLu8yl51iv-Ram7er9lKfWDtQsuNeLqbzEOQo0UlRNexaV0V2m8fYke8ubw3kNeR5XsRYiyr958OFwNgZ3RNfy-mNnO9P-4TFEF12NmNNEm4N6h0_DRZ-g74n-X2nGwx9emPv4wuy9kvQGeoCqc636BfKRE-51w2GFSrHAsOUJJ1dDryxZsxQOEGep3HGrVp_rTsVv7Vk3JxKxlzqt3hnBGDgi6suTZnJw69poVOIz6TPCTthRhj7XUu4heyKBSIeHsjBRC2_s3NwuZ4kKNCQ2JkVuBXz_hsRhDmbAnBi6WUFIJhLHO_bGgKbEASuU4vtj4FNKo_G8p-J1kYmCo0Pi72Csi3EikuocfjHFwfSD3cCbetr3V8Yp6OmSGkqX63FkSqzBoAcHFeD-iyCAkn0UJGqU-0o670ZoR-twkUDcSJPXDN2NYQfqiyb9ZknZ7j04w1ZfAyaE7NCiCc-lDt1ic79XyHunjOyLStgXIW30J4OEw_hAn86LlRHbYVhi-zBBTZWWnEl9piuUz0qtnN-qEd002DjNYaMy0aDAbL9oOYDdN8mHvnXq1aKove9I4Jy0WtlxeN8279ayz7NdDZZ9LrajY_YxIJJqdZtJIuRYTunEeDsFrORpu3RYRbFwpGnQbHeSLH1YvwOyOJRXhYYmVLJEGD2N9r5wkPbgbx2HoWsGjWj_DpkEAyg59eBJy4RYPJHvOsetBQABEWmGI7nhUDYTPdhrzVxqB_g4fQ9JkPzIbEhcoEZjmspGZcR4z4JxUDJCNdAz2aK4lR4P5WTkLtj2uXMDD_nzbl8r_DMcj23bjPiSe0Fubu-VIzjwr7JgPNyQ1FYhp5u4lpqkkBkGtfyAaUjCgFhg4FW-H3d3vPVMO--GxbhK9kN0QAcOE3ZqQR2dRz6NbhcvTyNfDxy0dFTRw-f_vxn04gjJB5ZEG3WfSzQv0VbqDYm6-NFYAzIxbDLoiCu34WAa2lckx5qxncXBhQj6Fro2gXGPXo4d32DvpQg7_RHQ-SF_WLqdxRCXF91NIqxYmFZsOJAuQ5m6TafzuNnQoJB3OQFoknv8Uy5O4FKuwazh1rvLrsj-1QEMi3sTrr9KxJkZy9EKXs92ndlb3edgfycLOffTil-gW2BvxeNiMQzqF1xJqFBKHDyatgwpXDX81HDwxkuMEaGPREIeQLuOlBJrL_20RD1e4Gu4tjQD8vRsb29UNG60DqpDvc-H4Z2oxeppm0KIwQNaCTtGUxxmvT807fXMnuVEf5QI5qTx9YRJh56GiWLoHC_zPMhoikMbAybIVWh9HtVgZGgImDmz0l9P4LgtpKNnKbQj_2ZKn2ZhOYKZLdt1P2Jq2Z2z76MtbRQTrpZpFb14zWVnh1LFCSFPAB7sqC1-u-KQOf2_SjEecztPccso8xZB2nkhLetyPn9aFuO-J_LCZydQeiroXx4Z8NxhDpbLoOpw2MbRCVB_TxfnLGNn1QD0To9TTChxK5AHNRRLDaj3xK1e0jd37uSmHTkT6QJVHFHEYMVLBcuV1MQcoy0wsvc1sRb",null],"logging":{"composer_session_id":"'+str(uuid.uuid4())+'"},"navigation_data":{"attribution_id_v2":"FeedsCometRoot.react,comet.most_recent_feed,tap_bookmark,1719641912186,189404,608920319153834,,"},"event_share_metadata":{"surface":"newsfeed"},"actor_id":"'+self.id+'","client_mutation_id":"3"},"feedLocation":"NEWSFEED","feedbackSource":1,"focusCommentID":null,"gridMediaWidth":null,"groupID":null,"scale":1,"privacySelectorRenderLocation":"COMET_STREAM","checkPhotosToReelsUpsellEligibility":false,"renderLocation":"homepage_stream","useDefaultActor":false,"inviteShortLinkKey":null,"isFeed":true,"isFundraiser":false,"isFunFactPost":false,"isGroup":false,"isEvent":false,"isTimeline":false,"isSocialLearning":false,"isPageNewsFeed":false,"isProfileReviews":false,"isWorkSharedDraft":false,"hashtag":null,"canUserManageOffers":false,"__relay_internal__pv__CometIsAdaptiveUFIEnabledrelayprovider":true,"__relay_internal__pv__CometUFIShareActionMigrationrelayprovider":true,"__relay_internal__pv__IncludeCommentWithAttachmentrelayprovider":true,"__relay_internal__pv__CometUFIReactionsEnableShortNamerelayprovider":false,"__relay_internal__pv__CometImmersivePhotoCanUserDisable3DMotionrelayprovider":false,"__relay_internal__pv__IsWorkUserrelayprovider":false,"__relay_internal__pv__IsMergQAPollsrelayprovider":false,"__relay_internal__pv__StoriesArmadilloReplyEnabledrelayprovider":true,"__relay_internal__pv__StoriesRingrelayprovider":false,"__relay_internal__pv__EventCometCardImage_prefetchEventImagerelayprovider":false}','server_timestamps': 'true','doc_id': '8167261726632010'}
            self.session.post("https://www.facebook.com/api/graphql/",headers=self.headers, data=data)
        except:
            pass

    def group(self, id: str):
        try:
            data = {'av':self.id,'fb_dtsg':self.fb_dtsg,'jazoest':self.jazoest,'fb_api_caller_class':'RelayModern','fb_api_req_friendly_name':'GroupCometJoinForumMutation','variables':'{"feedType":"DISCUSSION","groupID":"'+id+'","imageMediaType":"image/x-auto","input":{"action_source":"GROUP_MALL","attribution_id_v2":"CometGroupDiscussionRoot.react,comet.group,via_cold_start,1673041528761,114928,2361831622,","group_id":"'+id+'","group_share_tracking_params":{"app_id":"2220391788200892","exp_id":"null","is_from_share":false},"actor_id":"'+self.id+'","client_mutation_id":"1"},"inviteShortLinkKey":null,"isChainingRecommendationUnit":false,"isEntityMenu":true,"scale":2,"source":"GROUP_MALL","renderLocation":"group_mall","__relay_internal__pv__GroupsCometEntityMenuEmbeddedrelayprovider":true,"__relay_internal__pv__GlobalPanelEnabledrelayprovider":false}','server_timestamps':'true','doc_id':'5853134681430324','fb_api_analytics_tags':'["qpl_active_flow_ids=431626709"]',}
            self.session.post('https://www.facebook.com/api/graphql/',headers=self.headers, data=data)
        except:
            pass

    def comment(self, id, msg:str):
        try:
            data = {'av': self.id,'fb_dtsg': self.fb_dtsg,'jazoest': self.jazoest,'fb_api_caller_class': 'RelayModern','fb_api_req_friendly_name': 'useCometUFICreateCommentMutation','variables': fr'{{"feedLocation":"DEDICATED_COMMENTING_SURFACE","feedbackSource":110,"groupID":null,"input":{{"client_mutation_id":"4","actor_id":"{self.id}","attachments":null,"feedback_id":"{encode_to_base64(f"feedback:{id}")}","formatting_style":null,"message":{{"ranges":[],"text":"{msg}"}},"attribution_id_v2":"CometHomeRoot.react,comet.home,via_cold_start,1718688700413,194880,4748854339,,","vod_video_timestamp":null,"feedback_referrer":"/","is_tracking_encrypted":true,"tracking":["AZX1ZR3ETYfGknoE2E83CrSh9sg_1G8pbUK70jA-zjEIcfgLxA-C9xuQsGJ1l2Annds9fRCrLlpGUn0MG7aEbkcJS2ci6DaBTSLMtA78T9zR5Ys8RFc5kMcx42G_ikh8Fn-HLo3Qd-HI9oqVmVaqVzSasZBTgBDojRh-0Xs_FulJRLcrI_TQcp1nSSKzSdTqJjMN8GXcT8h0gTnYnUcDs7bsMAGbyuDJdelgAlQw33iNoeyqlsnBq7hDb7Xev6cASboFzU63nUxSs2gPkibXc5a9kXmjqZQuyqDYLfjG9eMcjwPo6U9i9LhNKoZwlyuQA7-8ej9sRmbiXBfLYXtoHp6IqQktunSF92SdR53K-3wQJ7PoBGLThsd_qqTlCYnRWEoVJeYZ9fyznzz4mT6uD2Mbyc8Vp_v_jbbPWk0liI0EIm3dZSk4g3ik_SVzKuOE3dS64yJegVOQXlX7dKMDDJc7P5Be6abulUVqLoSZ-cUCcb7UKGRa5MAvF65gz-XTkwXW5XuhaqwK5ILPhzwKwcj3h-Ndyc0URU_FJMzzxaJ9SDaOa9vL9dKUviP7S0nnig0sPLa5KQgx81BnxbiQsAbmAQMr2cxYoNOXFMmjB_v-amsNBV6KkES74gA7LI0bo56DPEA9smlngWdtnvOgaqlsaSLPcRsS0FKO3qHAYNRBwWvMJpJX8SppIR1KiqmVKgeQavEMM6XMElJc9PDxHNZDfJkKZaYTJT8_qFIuFJVqX6J9DFnqXXVaFH4Wclq8IKZ01mayFbAFbfJarH28k_qLIxS8hOgq9VKNW5LW7XuIaMZ1Z17XlqZ96HT9TtCAcze9kBS9kMJewNCl-WYFvPCTCnwzQZ-HRVOM04vrQOgSPud7vlA3OqD4YY2PSz_ioWSbk98vbJ4c7WVHiFYwQsgQFvMzwES20hKPDrREYks5fAPVrHLuDK1doffY1hPTWF2KkSt0uERAcZIibeD5058uKSonW1fPurOnsTpAg8TfALFu1QlkcNt1X4dOoGpYmBR7HGIONwQwv5-peC8F758ujTTWWowBqXzJlA2boriCvdZkvS15rEnUN57lyO8gINQ5heiMCQN8NbHMmrY_ihJD3bdM4s2TGnWH4HBC2hi0jaIOJ8AoCXHQMaMdrGE1st7Y3R_T6Obg6VnabLn8Q-zZfToKdkiyaR9zqsVB8VsMrAtEz0yiGpaOF3KdI2sxvii3Q5XWIYN6gyDXsXVykFS25PsjPmXCF8V1mS7x6e9N9PtNTWwT8IGBZp9frOTQN2O52dOhPdsuCHAf0srrBVHbyYfCMYbOqYEEXQG0pNAmG_wqbTxNew9kTsXDRzYKW-NmEJcvy_xh1dDwg8xJc58Cl71e-rau3iP7o8mWhVSaxi4Bi6LAuj4UKVCt3IYCfm9AR1d5LqBFWU9LrJbRZSMlmUYwZf7PlrKmpnCnZvuismiL7DH3cnUjP0lWAvhy3gxZm1MK8KyRzWmGnTNqaVlL37c2xoE4YSyponeOu5D-lRl_Dp_C2PyR1kG6G0TCWS66UbU89Fu1qmwWjeQwYhzj2Jly9LRyClAbe86VJhIZE18YLPB-n1ng78qz7hHtQ8qT4ejY4csEjSRjjnHdz8U-06qErY-CXNNtVtzpYGuzZ1ZaXqzAQkUcREm98KR8c1vaXaQXumtDklMVgs76gLqZyiG1eCRbOQ6_EcQv7GeFnq5UIqoMH_Xzc78otBTvC5j3aCs5Pvf6k3gQ5ZU7E4uFVhZA7xoyD8sPX6rhdGL8JmLKJSGZQM5ccWpfpDJ5RWJp0bIJdnAJQ8gsYMRAI2OBxx2m2c76lNiUnB750dMe2H3pFzFQVkWQLkmGVY37cgmRNHyXboDMQ1U2nlbNH017dmklJCk4jVU8aA9Gpo8oHw","{{\"assistant_caller\":\"comet_above_composer\",\"conversation_guide_session_id\":\"{uuid.uuid4()}\",\"conversation_guide_shown\":null}}"],"feedback_source":"DEDICATED_COMMENTING_SURFACE","idempotence_token":"client:{uuid.uuid4()}","session_id":"{uuid.uuid4()}"}},"inviteShortLinkKey":null,"renderLocation":null,"scale":1,"useDefaultActor":false,"focusCommentID":null}}','server_timestamps': 'true','doc_id': '7994085080671282',}
            self.session.post('https://www.facebook.com/api/graphql/', headers=self.headers, data=data)
        except:
            pass
    
    def page_review(self, id, msg:str):
        try:
            data = {'av':self.id,'fb_dtsg': self.fb_dtsg,'jazoest': self.jazoest,'variables': '{"input":{"composer_entry_point":"inline_composer","composer_source_surface":"page_recommendation_tab","source":"WWW","audience":{"privacy":{"allow":[],"base_state":"EVERYONE","deny":[],"tag_expansion_state":"UNSPECIFIED"}},"message":{"ranges":[],"text":"' +msg+ '"},"with_tags_ids":[],"text_format_preset_id":"0","page_recommendation":{"page_id":"'+id+'","rec_type":"POSITIVE"},"actor_id":"'+self.id+'","client_mutation_id":"1"},"feedLocation":"PAGE_SURFACE_RECOMMENDATIONS","feedbackSource":0,"scale":1,"privacySelectorRenderLocation":"COMET_STREAM","renderLocation":"timeline","UFI2CommentsProvider_commentsKey":"ProfileCometReviewsTabRoute","hashtag":null,"canUserManageOffers":false}','doc_id': '5737011653023776'}
            self.session.post('https://www.facebook.com/api/graphql/',headers=self.headers, data=data)
        except:
            pass
    
    def sharend(self, id, msg:str):
        try:
            data = {
                'av':self.id,
                'fb_dtsg': self.fb_dtsg,
                'jazoest': self.jazoest,
                'variables': '{"input":{"composer_entry_point":"share_modal","composer_source_surface":"feed_story","composer_type":"share","idempotence_token":"'+str(uuid.uuid4())+'_FEED","source":"WWW","attachments":[{"link":{"share_scrape_data":"{\"share_type\":22,\"share_params\":['+id+']}"}}],"reshare_original_post":"RESHARE_ORIGINAL_POST","audience":{"privacy":{"allow":[],"base_state":"EVERYONE","deny":[],"tag_expansion_state":"UNSPECIFIED"}},"is_tracking_encrypted":true,"tracking":["AZXEWGOa5BgU9Y4vr1ZzQbWSdaLzfI3EMNtpYwO1FzzHdeHKOCyc4dd677vkeHFmNfgBKbJ7vHSB96dnQh4fQ0-dZB3zHFN1qxxhg5F_1K8RShMHcVDNADUhhRzdkG2C6nujeGpnPkw0d1krhlgwq2xFc1lM0OLqo_qr2lW9Oci9BzC3ZkT3Jqt1m8-2vpAKwqUvoSfSrma8Y5zA1x9ZF0HLeHojOeodv_w5-S9hcdgy3gvF5o4lTdzfp3leby36PkwOyJqCOI51h6jp-cH0WUubXMbH2bVM-v9Mv7kHw9_yC8dP5b_tjerx7ggHtnhr1KtOEiolPmCkQiapP5dX9phUaW908T9Kh1aDk4sK7cd7QfVaGj6LSOiHS599VsgvvbHopOVxH80a96LkuhH4t0DLc8QjljGwAmublnMVuvUbVaiChuyjzAIQe-xj2C7yMGzxmOacqR7yaepDUI-fpRZAzkcfVUdumVzbjWtCYGZLJgw4lAKVv6Y37tBedtAGHF7P7EEdQSXOX6ADg0cEYUeusp9Oho1SAbz_rVGiJc-oSkWY6S2XwD5vBXwV9lfdg6vuH3DKDcIDDoua3xXN7sYbVOw3ClcTbxMAmQqE8ClYrlbIXNp-QCW2Rr_3ro3VgYqNo1UkRyDXhCHs8rWUNY6N-bhMWCHI9CPOEebbqXnSRayKmgxYrDOIuHIzyHujUBYLnEikCYIfVwaeEB4X-Et3ZZvgoHdaZAhSO3YNFLYjyimb1tR8A-Pm2KoKwIF6equnjWWLHKoovFhbhQLRmjYYBJUhP4n0yLunWLnPwn8e7ev9h4fsGMREmonEbizxwrsr1bqpDBjHWliiPTPHDdlJNVko7anmeT1txjmTaOrA8oejbs1hDeNEZoEuL2vkN7HdjiJFhLu2yTNw2Rc3WHHOb8FcFlwTOzCDUHGDbv_bV8iAlybhEZFE-3kmoMrw7kXPjwC8D_x4VRW1BQ1wVEsYFjBrLOjk05nsuuU0X5aD5DJi3zrL3bET2eGIIlbXdXvn57Q2JtCnnS0uRyaB2pHghXTkrT2l_1fPqTJIhJOi6YQDymf2paNIUd1Fe3fDZBp1D4VMsNphQr4mSIANKGHZP29cmWJox94ztH7mrLIhSRiSzs_DrTb5o5YH6AwBkg9XzNdlM7uMxAPB9lbqVAPWXEBANhoAHvYjQI1-61myVarQBrk36dbz15PASG1c5Fina9vATWju6Bfj7PjoqJ4rARcZBJOO011e2eLy4yekMuG8bD5TvEwuiRn_M23iuC-k_w77abKvcW4MJX1f4Gfv9S4C_8N4pSiWOPNRgHPJWEQ6vhhu3euzWVSKYJ5jmfeqA9jFd_U6qVkEXenI0ofFBXw-fzjoWoRHy5y8xBG9qg",null],"message":{"ranges":[],"text":"'+msg+'"},"logging":{"composer_session_id":"'+str(uuid.uuid4())+'"},"navigation_data":{"attribution_id_v2":"CometSinglePostDialogRoot.react,comet.post.single_dialog,via_cold_start,1743945123087,176702,,,"},"event_share_metadata":{"surface":"newsfeed"},"actor_id":"'+self.id+'","client_mutation_id":"1"},"feedLocation":"NEWSFEED","feedbackSource":1,"focusCommentID":null,"gridMediaWidth":null,"groupID":null,"scale":1,"privacySelectorRenderLocation":"COMET_STREAM","checkPhotosToReelsUpsellEligibility":false,"renderLocation":"homepage_stream","useDefaultActor":false,"inviteShortLinkKey":null,"isFeed":true,"isFundraiser":false,"isFunFactPost":false,"isGroup":false,"isEvent":false,"isTimeline":false,"isSocialLearning":false,"isPageNewsFeed":false,"isProfileReviews":false,"isWorkSharedDraft":false,"hashtag":null,"canUserManageOffers":false,"__relay_internal__pv__CometUFIShareActionMigrationrelayprovider":true,"__relay_internal__pv__GHLShouldChangeSponsoredDataFieldNamerelayprovider":false,"__relay_internal__pv__GHLShouldChangeAdIdFieldNamerelayprovider":false,"__relay_internal__pv__CometIsReplyPagerDisabledrelayprovider":false,"__relay_internal__pv__IsWorkUserrelayprovider":false,"__relay_internal__pv__CometUFIReactionsEnableShortNamerelayprovider":false,"__relay_internal__pv__FBReels_deprecate_short_form_video_context_gkrelayprovider":true,"__relay_internal__pv__CometFeedStoryDynamicResolutionPhotoAttachmentRenderer_experimentWidthrelayprovider":500,"__relay_internal__pv__CometImmersivePhotoCanUserDisable3DMotionrelayprovider":false,"__relay_internal__pv__WorkCometIsEmployeeGKProviderrelayprovider":false,"__relay_internal__pv__IsMergQAPollsrelayprovider":false,"__relay_internal__pv__FBReelsMediaFooter_comet_enable_reels_ads_gkrelayprovider":true,"__relay_internal__pv__StoriesArmadilloReplyEnabledrelayprovider":false,"__relay_internal__pv__CometFeedPYMKHScrollInitialPaginationCountrelayprovider":10,"__relay_internal__pv__FBReelsIFUTileContent_reelsIFUPlayOnHoverrelayprovider":true,"__relay_internal__pv__GHLShouldChangeSponsoredAuctionDistanceFieldNamerelayprovider":true}',
                'doc_id': '29449903277934341'
            }
            self.session.post('https://www.facebook.com/api/graphql/',headers=self.headers, data=data)
        except: 
            pass

    def checkDissmiss(self):
        try:
            response = self.session.get('https://www.facebook.com/', headers=self.headers)
            if '601051028565049' in response.text: return 'Dissmiss'
            if '1501092823525282' in response.text: return 'Checkpoint282'
            if '828281030927956' in response.text: return 'Checkpoint956'
            if 'title="Log in to Facebook">' in response.text: return 'CookieOut'
            else: return 'Biblock'
        except: 
            pass
    
    def clickDissMiss(self):
        try:
            data = {"av": self.id,"fb_dtsg": self.fb_dtsg,"jazoest": self.jazoest,"fb_api_caller_class": "RelayModern","fb_api_req_friendly_name": "FBScrapingWarningMutation","variables": "{}","server_timestamps": "true","doc_id": "6339492849481770"}
            self.session.post('https://www.facebook.com/api/graphql/', headers=self.headers, data=data)
        except: 
            pass



import re, sys, time, base64, random
from pystyle import Colors, Colorate
from colorama import Fore


import re, sys, time, base64, random
from colorama import Fore
from pystyle import Colors, Colorate

def encode_to_base64(text: str):
    return base64.b64encode(text.encode()).decode()

def prints(r, g, b, text, end="\n"):
    print(f"\033[38;2;{r};{g};{b}m{text}\033[0m", end=end)

class PHUOCANCODER:
    def __init__(self, cookie: str):
        try:
            self.fb_dtsg = ''
            self.jazoest = ''
            self.cookie = cookie
            self.session = requests.Session()
            self.fb_id = self.cookie.split('c_user=')[1].split(';')[0]
            self.id = self.cookie.split('c_user=')[1].split(';')[0]
            self.headers = {'authority': 'www.facebook.com', 'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9', 'accept-language': 'vi', 'sec-ch-prefers-color-scheme': 'light', 'sec-ch-ua': '"Chromium";v="106", "Google Chrome";v="106", "Not;A=Brand";v="99"', 'sec-ch-ua-mobile': '?0', 'sec-ch-ua-platform': '"Windows"', 'sec-fetch-dest': 'document', 'sec-fetch-mode': 'navigate', 'sec-fetch-site': 'none', 'sec-fetch-user': '?1', 'upgrade-insecure-requests': '1', 'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36', 'viewport-width': '1366', 'Cookie': self.cookie}
            self.headers_base = {
                'authority': 'www.facebook.com',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                'accept-language': 'vi-VN,vi;q=0.9,en;q=0.8',
                'cache-control': 'max-age=0',
                'sec-ch-ua': '"Chromium";v="118", "Google Chrome";v="118", "Not=A?Brand";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'none',
                'sec-fetch-user': '?1',
                'upgrade-insecure-requests': '1',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
                'cookie': self.cookie
            }
            url = self.session.get(f'https://www.facebook.com/{self.id}', headers=self.headers).url
            response = self.session.get(url, headers=self.headers).text
            matches = re.findall(r'\["DTSGInitialData",\[\],\{"token":"(.*?)"\}', response)
            if len(matches) > 0:
                self.fb_dtsg += matches[0]
                self.jazoest += re.findall(r'jazoest=(.*?)\"', response)[0]
        except:
            pass


    # ==== Lấy post ID từ link ====
    def get_post_id(self, link):
        try:
            getuid = requests.post('https://id.traodoisub.com/api.php', data={'link': link}).json()
            if 'success' in getuid:
                return getuid['id']
            else:
                prints(255,0,0,"Link bài viết đã bị die...")
                sleep(2)
                return None
        except Exception as e:
            prints(255,0,0,f"[X] Lỗi lấy ID: {e}")
            return None

    # ==== Gửi reaction GraphQL ====
    def react_post(self, object_id, type_react):
        react_map = {
            "LIKE": "1635855486666999",
            "LOVE": "1678524932434102",
            "CARE": "613557422527858",
            "HAHA": "115940658764963",
            "WOW": "478547315650144",
            "SAD": "908563459236466",
            "ANGRY": "444813342392137"
        }

        react_id = react_map.get(type_react.upper())
        if not react_id:
            #prints(255, 0, 0, f"[X] Loại reaction không hợp lệ: {type_react}")
            return False

        headers = self.headers_base.copy()
        headers.update({
            "x-fb-friendly-name": "CometUFIFeedbackReactMutation",
            "x-fb-lsd": self.fb_dtsg[:8],
            "referer": f"https://www.facebook.com/{object_id}",
        })

        payload = {
            "av": self.fb_id,
            "__user": self.fb_id,
            "fb_dtsg": self.fb_dtsg,
            "jazoest": self.jazoest,
            "lsd": self.fb_dtsg[:8],
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": "CometUFIFeedbackReactMutation",
            "variables": f'{{"input":{{"feedback_id":"{encode_to_base64("feedback:" + object_id)}","feedback_reaction_id":"{react_id}","actor_id":"{self.fb_id}","client_mutation_id":"1"}},"useDefaultActor":false}}',
            "server_timestamps": "true",
            "doc_id": "24034997962776771"  # doc_id mới hơn, fix lỗi 400
        }

       # prints(255, 255, 0, f"[→] Đang thả {type_react.upper()} vào {object_id[:20]}...", end="\r")
        try:
            res = self.session.post("https://www.facebook.com/api/graphql/", headers=headers, data=payload)
            #print(res.json())
            if 'feedback_react' in res.text:
                #prints(0, 255, 0, f"[✓] Thành công thả {type_react.upper()} vào {object_id}", end="\r")
                return True
            else:
              #  prints(255, 0, 0, f"[X] Thất bại ({res.status_code}) → {res.text[:100]}")
                return False
        except Exception as e:
            prints(255, 0, 0, f"[X] Lỗi khi thả cảm xúc: {e}")
            return False

    # ==== React tự động (link + loại react) ====
    def react_auto(self, link, type_react):
        object_id = self.get_post_id(link)
        if not object_id:
            return False
        return self.react_post(object_id, type_react)


from pystyle import Colors, Colorate
import random, re, requests, sys, time, os

# ========== CÁC HÀM TIỆN ÍCH ==========
def read_file(filename):
    return open(filename, "r").read().strip() if os.path.exists(filename) else ""

def save_file(filename, data):
    open(filename, "w").write(data.strip())

# ========== DANH SÁCH MÀU NGẪU NHIÊN ==========
gradients_list = [
    Colors.red_to_yellow,
    Colors.yellow_to_red,
    Colors.green_to_blue,
    Colors.blue_to_cyan,
    Colors.green_to_white,
    Colors.cyan_to_green, 
    Colors.rainbow,
    
    Colors.red_to_white,
    Colors.purple_to_blue,
    Colors.yellow_to_green,
    Colors.purple_to_red,
]
def random_grad():
    return random.choice(gradients_list)

# ========== DELAY CÓ MÀU ==========
def Delay(s):
    while s > 0:
        text = f"[PAPDZAI] [CHO DOI LA HANH PHUC] ~> [{s} giây]"
        print(Colorate.Horizontal(random_grad(), text), end="\r")
        time.sleep(1)
        s -= 1
    print(" " * 80, end="\r")  # xoá dòng sau khi xong

# ===========Banner =============
def prints(r, g, b, text="text", end="\n"):
    print(f"\033[38;2;{r};{g};{b}m{text}\033[0m", end=end)


# ========== CHẠY CHÍNH ==========
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, threading
from time import sleep as Delay
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich import print
import time

console = Console()

def banner():
    banner_text = """
╔══════════════════════════════════════════════════════════════╗
║                 GOLIKE FACEBOOK AUTOMATION                  ║
║                     BY PAP - VIP TOOL                       ║
║                 https://github.com/papcoder                 ║
╚══════════════════════════════════════════════════════════════╝
"""
    console.print(Panel.fit(banner_text, border_style="#9B00FF", style="bold #00FFFF"))

class JobTracker:
    def __init__(self):
        self.jobs = []
        self.thread_stats = {}
        self.total_earned = 0
        
    def add_job(self, thread_idx, job_type, target, status, earned):
        self.jobs.append({
            "thread": thread_idx,
            "type": job_type.upper(),
            "target": target,
            "status": status,
            "earned": earned,
            "time": time.strftime("%H:%M:%S")
        })
        # Giữ 15 dòng gần nhất
        if len(self.jobs) > 15:
            self.jobs.pop(0)
            
        if status == "SUCCESS":
            self.total_earned += earned
            
    def update_thread_stat(self, thread_idx, jobs_done=0, total_earned=0, status="Running"):
        if thread_idx not in self.thread_stats:
            self.thread_stats[thread_idx] = {
                "jobs_done": 0,
                "total_earned": 0,
                "status": status
            }
        
        if jobs_done > 0:
            self.thread_stats[thread_idx]["jobs_done"] += jobs_done
        if total_earned > 0:
            self.thread_stats[thread_idx]["total_earned"] += total_earned
        if status:
            self.thread_stats[thread_idx]["status"] = status
    
    def create_table(self):
        table = Table(show_header=True, header_style="bold cyan", title="GOLIKE FACEBOOK - LIVE DASHBOARD")
        
        # Cột cho job history
        table.add_column("#", style="dim", width=4)
        table.add_column("Time", style="dim", width=8)
        table.add_column("Luồng", style="green", width=8)
        table.add_column("Job Type", style="yellow", width=12)
        table.add_column("Target", style="white", width=25)
        table.add_column("Status", style="bold", width=10)
        table.add_column("Earned", style="bold green", width=10)
        
        # Thêm dữ liệu job
        for i, job in enumerate(self.jobs, 1):
            status_style = "bold green" if job["status"] == "SUCCESS" else "bold red"
            earned_text = f"+{job['earned']}Đ" if job["status"] == "SUCCESS" else "+0Đ"
            
            table.add_row(
                str(i),
                job["time"],
                f"L{job['thread']}",
                job["type"],
                job["target"][:23] + "..." if len(job["target"]) > 23 else job["target"],
                f"[{status_style}]{job['status']}[/]",
                f"[bold green]{earned_text}[/]" if job["status"] == "SUCCESS" else "[dim]+0Đ[/]"
            )
        
        # Thêm dòng tổng kết
        total_threads = len(self.thread_stats)
        total_jobs = sum(stat["jobs_done"] for stat in self.thread_stats.values())
        
        table.add_row("", "", "", "", "", "", "", style="bold cyan")
        table.add_row(
            "TOTAL",
            "",
            f"{total_threads} Luồng",
            f"{total_jobs} Jobs",
            "",
            "Tổng tiền:",
            f"[bold cyan]{self.total_earned}Đ[/]",
            style="bold yellow"
        )
        
        return table

class MAINCHAYGOLIKEFACEBOOKBYPAP:
    def __init__(self):
        banner()
        self.auth = ""
        self.cookies = []
        self.proxies = []
        self.job_choice = "4"
        self.delay = 10
        self.tracker = JobTracker()
        self.running = True  # Thêm biến điều khiển

    # ====== HÀM TIỆN ÍCH ======
    def read_file(self, path):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        return ""

    def read_lines(self, path):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return [x.strip() for x in f if x.strip()]
        return []

    def save_file(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            f.write(data.strip())

    
    # ====== NHẬP THÔNG TIN ======
    def get_auth(self):
        saved = self.read_file("Auth_Golike.txt")
        if saved:
            console.print(Panel.fit(f"[cyan]Đã tìm thấy Auth Golike lưu trước đó[/]\n[white]{saved[:60]}...", border_style="cyan"))
            chon = input("1. Dùng lại  |  2. Nhập mới → ").strip()
            if chon == "1":
                self.auth = saved
            else:
                self.auth = input("Nhập Auth Golike mới: ").strip()
                self.save_file("Auth_Golike.txt", self.auth)
        else:
            self.auth = input("Nhập Auth Golike: ").strip()
            self.save_file("Auth_Golike.txt", self.auth)

    def get_proxies(self):
        self.proxies = self.read_lines("proxy.txt")
        if self.proxies:
            console.print(Panel.fit(f"[green]Đã nạp {len(self.proxies)} proxy từ proxy.txt[/]", border_style="green"))
        else:
            console.print(Panel.fit("[yellow]Không có proxy.txt — chạy không proxy[/]", border_style="#9B00FF"))

    def get_cookies(self):
        console.print(Panel.fit("[#00FFFF]Nhập Cookie Facebook (Enter để bỏ qua, nhập nhiều để chạy đa luồng)[/]", border_style="#FF0033"))
        while True:
            c = input("Cookie FB: ").strip()
            if not c:
                break
            self.cookies.append(c)

        if not self.cookies:
            saved = self.read_file("cookie.txt")
            if saved:
                console.print(Panel.fit(f"[cyan]Đã có cookie lưu sẵn[/]\n[white]{saved[:80]}...", border_style="cyan"))
                chon = input("1. Dùng lại cookie đã lưu  |  2. Nhập mới → ").strip()
                if chon == "1":
                    self.cookies = [saved]
                else:
                    c = input("Nhập Cookie Facebook: ").strip()
                    self.cookies = [c]
                    self.save_file("cookie.txt", c)
            else:
                c = input("Nhập Cookie Facebook: ").strip()
                self.cookies = [c]
                self.save_file("cookie.txt", c)

    def get_job_choice(self):
        console.print(Panel(
            "[#FF69B4]Chọn loại job muốn làm:[/]\n"
            "[white][1][/]. Reaction\n"
            "[white][2][/]. Like Page\n"
            "[white][3][/]. Follow\n"
            "[white][4][/]. Tất cả", border_style="#FF69B4"
        ))
        self.job_choice = input("Chọn: ").strip() or "4"

    def get_delay(self):
        self.delay = int(input("Nhập delay (giây): ") or "10")

    # ====== THREAD CHẠY CHÍNH ======
    def run_cookie(self, cookie, auth, proxy, job_choice, delay, idx):
        try:
            # Khởi tạo luồng
            self.tracker.update_thread_stat(idx, status="Đang khởi động...")

            # Giả lập các module - THAY THẾ BẰNG CODE THẬT CỦA BẠN
            gl = MODULE_GOLIKE_FACEBOOK()
            gl.setupauth(auth)
            acc = gl.get_account()
            
            # KIỂM TRA AUTH - SỬA LẠI LOGIC
            if not acc or acc.get('status') != 200:
                self.tracker.update_thread_stat(idx, status="Lỗi Auth - Vẫn chạy")
                # KHÔNG return ở đây, tiếp tục chạy để test
                console.print(f"[yellow][Luồng {idx}] Auth có vấn đề nhưng vẫn tiếp tục chạy...[/]")

            fb = Facebook(cookie)
            uidacc = fb.info()
            
            
            
            fb_name = uidacc.get("name", "Unknown")
            fb_id = cookie.split('c_user=')[1].split(';')[0] if 'c_user=' in cookie else "Unknown"
            console.print(f"[green][Luồng {idx}] Kết nối thành công: {fb_name}[/]")
            time.sleep(3)
            stt = 0
            done_jobs = set()

            # VÒNG LẶP CHÍNH - CHẠY LIÊN TỤC
            while self.running:
                try:
                    self.tracker.update_thread_stat(idx, status="Đang get job...")
                    
                    # LẤY JOB - THÊM XỬ LÝ LỖI
                    job_data = {}
                    try:
                        job_data = gl.get_jobs()
                    except Exception as e:
                        console.print(f"[red][Luồng {idx}] Lỗi get jobs: {e}[/]")
                        job_data = {}

                    # KIỂM TRA JOB DATA - LOGIC LINH HOẠT HƠN
                    if not job_data or not isinstance(job_data, dict) or not job_data.get("data"):
                        self.tracker.update_thread_stat(idx, status="Đang chờ job...")
                        Delay(10)
                        continue

                    self.tracker.update_thread_stat(idx, status="Đang xử lý job...")

                    for job in job_data.get("data", []):
                        if not self.running:
                            break
                            
                        stt += 1
                        job_type = job.get("type", "unknown")
                        target = job.get("object_id", "unknown")
                        giajob = job.get("price_after_cost", 0)

                        # lọc job
                        if job_choice == "1" and job_type not in ["like","love","care","haha","wow","sad","angry"]:
                            continue
                        elif job_choice == "2" and job_type != "_page":
                            continue
                        elif job_choice == "3" and job_type != "follow":
                            continue

                        # tránh trùng
                        if target in done_jobs:
                            try:
                                gl.bao_loi(target)
                            except:
                                pass
                            continue
                        done_jobs.add(target)

                        # XỬ LÝ JOB - THÊM TRY CATCH
                        success = False
                        try:
                            if job_type == "_page":
                                success = fb.likepage(target) or fb.follow(target)
                            elif job_type in ["like","love","care","haha","wow","sad","angry"]:
                                success = het.react_auto(job.get("link"), job_type)
                            elif job_type == "follow":
                                success = fb.follow(target) or fb.likepage(target)
                        except Exception as job_error:
                            console.print(f"[red][Luồng {idx}] Lỗi xử lý job: {job_error}[/]")
                            success = False

                        # CẬP NHẬT KẾT QUẢ
                        if success:
                            Delay(2)  # Giảm delay để test
                            try:
                                res = gl.hoan_thanh(target)
                                if res and res.get("success"):
                                    self.tracker.add_job(idx, job_type, target, "SUCCESS", giajob)
                                    self.tracker.update_thread_stat(idx, jobs_done=1, total_earned=giajob, status="Thành công - Đang chờ job...")
                                    console.print(f"[green][Luồng {idx}] Job {stt} thành công: +{giajob}Đ[/]")
                                else:
                                    self.tracker.add_job(idx, job_type, target, "FAIL", 0)
                                    self.tracker.update_thread_stat(idx, status="Báo lỗi job")
                                    try:
                                        gl.bao_loi(target)
                                    except:
                                        pass
                            except Exception as e:
                                self.tracker.add_job(idx, job_type, target, "FAIL", 0)
                                console.print(f"[red][Luồng {idx}] Lỗi hoàn thành job: {e}[/]")
                        else:
                            self.tracker.add_job(idx, job_type, target, "FAIL", 0)
                            self.tracker.update_thread_stat(idx, status="Job thất bại")
                            try:
                                gl.bao_loi(target)
                            except:
                                pass

                        # DELAY GIỮA CÁC JOB
                        if self.running:
                            self.tracker.update_thread_stat(idx, status=f"Delay {delay}s...")
                            for i in range(delay):
                                if not self.running:
                                    break
                                Delay(1)
                            
                except Exception as e:
                    console.print(f"[red][Luồng {idx}] Lỗi trong vòng lặp: {e}[/]")
                    Delay(5)  # Chờ 5s nếu có lỗi rồi tiếp tục

        except Exception as e:
            console.print(f"[red][Luồng {idx}] Lỗi nghiêm trọng: {e}[/]")
            self.tracker.update_thread_stat(idx, status=f"Lỗi: {str(e)[:20]}...")

    # ====== CHẠY CHÍNH ======
    def start(self):
        try:
            self.get_auth()
            self.get_proxies()
            self.get_cookies()
            self.get_job_choice()
            self.get_delay()

            # Hiển thị thông tin bắt đầu
            start_info = Panel.fit(
                f"[green]• {len(self.cookies)} Cookie[/] | [yellow]{len(self.proxies)} Proxy[/] | "
                f"[magenta]Job: {self.job_choice}[/] | [blue]Delay: {self.delay}s[/]\n"
                f"[cyan]Đang khởi chạy {len(self.cookies)} luồng...[/]",
                title="GOLIKE AUTOMATION STARTED",
                border_style="green"
            )
            console.print(start_info)
            Delay(2)

            threads = []
            
            # Sử dụng Live display với 1 table duy nhất
            with Live(self.tracker.create_table(), refresh_per_second=4, screen=True) as live:
                # Khởi chạy threads
                for i, cookie in enumerate(self.cookies, start=1):
                    proxy = self.proxies[i-1] if i-1 < len(self.proxies) else None
                    t = threading.Thread(
                        target=self.run_cookie, 
                        args=(cookie, self.auth, proxy, self.job_choice, self.delay, i)
                    )
                    t.daemon = True
                    threads.append(t)
                    t.start()
                    Delay(1)  # Delay giữa các luồng
                
                console.print(f"[green]✓ Đã khởi chạy {len(threads)} luồng[/]")
                
                # Cập nhật live display liên tục
                try:
                    while any(t.is_alive() for t in threads) and self.running:
                        live.update(self.tracker.create_table())
                        time.sleep(0.25)
                except KeyboardInterrupt:
                    console.print("\n[yellow]Đang dừng các luồng...[/]")
                    self.running = False
                    
                # Chờ các thread kết thúc
                for t in threads:
                    t.join(timeout=5)

        except KeyboardInterrupt:
            console.print("\n[red]Đã dừng chương trình![/]")
            self.running = False
        except Exception as e:
            console.print(f"\n[red]Lỗi khởi chạy: {e}[/]")
            self.running = False

        console.print(Panel.fit("[green]Chương trình đã kết thúc![/]", border_style="green"))

# ====== KHỞI CHẠY ======
if __name__ == "__main__":
    try:
        MAINCHAYGOLIKEFACEBOOKBYPAP().start()
    except KeyboardInterrupt:
        console.print("\n[red]Đã dừng chương trình![/]")
    except Exception as e:
        console.print(f"\n[red]Lỗi: {e}[/]")
        
        
