# -*- coding: utf-8 -*-
"""
橙子短剧 · TVBox / OK影视 双壳兼容源（蜘蛛模板骨架）

站点：api.cztvapp.com（APK com.aidrama.mobile 的原生 REST 接口，无加密、无签名头）
形态：JSON 接口站，没有 HTML 可解析 → 骨架保留，解析层换成 JSON。

接口（2026-11-08 全部实测）：
    POST auth/guest                     {install_id, platform}  → access_token(900s)
    GET  config/public                  免鉴权                   → brand / 域名表
    GET  categories                                             → AI短剧 / AI漫剧 / AI魔改
    GET  dramas?category_id=&page=&sort=                        → 分类列表（20/页，带 total）
    GET  dramas?q=&page=                                         → 搜索（20/页，带 total）
    GET  dramas/{id}                                            → 详情
    GET  dramas/{id}/episodes?page=                              → 剧集（20/页，带 total）
    GET  playback/episodes/{episode_id}                          → playback_url（签名 HLS，20 分钟）
    GET  recommend/feed                                          → 首页流（10 条，非分页）

实测要点（写源时踩过的，别改回去）：
  1. ★ 任何**未知查询参数**一律 HTTP 400 / code 1001（status / year / region / tag 全部拒）。
     所以筛选值必须白名单，脏值必须回落默认，绝不能把壳传来的值原样拼进 URL。
  2. sort 合法枚举只有 latest / hot / shuffle / recommend。recommend 在游客态退化成 hot
     （前 8 条重合 6 条），放上去等于同一个按钮 → 只留 latest / hot / shuffle（首条互不相同）。
  3. 播放清单是**媒体清单**（含 #EXTINF，不是 master），分片是裸相对名 seg_00000.ts，
     token 藏在路径里。以清单自身 URL 为基准 urljoin 可正确解析（实测首片 1,490,276B，首字节 0x47）
     → 默认直连，proxy:// 只在 extend={"m3u8":"proxy"} 时启用。
  4. 封面在 Bunny CDN，webp 格式，**握手约 25% 概率 SSL EOF**（实测 4 次里挂 1 次）
     → 取图必须重试，且本机图片服务也要重试。
  5. 站点是 18+ 成人向，按用户固化约定做内容脱敏（BLOCK_KW / BLOCK_VAR / _blocked）。
"""

import hashlib
import json
import re
import sys

try:
    import requests as _requests
except Exception:
    _requests = None

try:
    import threading as _th
except Exception:
    _th = None

try:
    import socketserver as _sock
except Exception:
    _sock = None

try:
    import http.server as _httpsrv
except Exception:
    _httpsrv = None

try:
    from urllib.parse import quote as _quote
    from urllib.parse import unquote as _unquote
    from urllib.parse import urljoin as _urljoin
except Exception:
    try:
        from urllib import quote as _quote
        from urllib import unquote as _unquote
    except Exception:
        def _quote(s, safe=""):
            return s

        def _unquote(s):
            return s

    def _urljoin(base, rel):
        if rel.startswith("http"):
            return rel
        cut = base.rfind("/")
        return (base[:cut + 1] if cut > 8 else base + "/") + rel

# ★★★ 双壳兼容基类（2026-11-02 固化）：OK影视/影视仓 严格按 base.spider 反射检查，
#     纯独立类会被判「加载不出来」；TVBox/FongMi 侧没有 base.spider。
#     写成「能继承就继承，继承不到退回本地空壳」，两边都能跑。
try:
    sys.path.append("..")
    from base.spider import Spider as _BaseSpider
except Exception:
    class _BaseSpider(object):
        """无 base.spider 时的本地空壳，保证独立类也能被壳反射实例化。"""

        def getProxyUrl(self):
            return ""

        def localProxy(self, param=None, *args, **kwargs):
            return [404, "text/plain", b"", None]

        def init(self, extend=""):
            return self

        def destroy(self):
            return None


# ======================================================================
# 一、站点常量
# ======================================================================
NAME = "橙子短剧"
SITE = "https://czfxa.com"
API = "https://api.cztvapp.com/api/v1"
UA = ("Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

# 封面取图模式：
#   direct = 直接把签名图地址交给壳（默认）。壳的 OkHttp 有连接池 + retryOnConnectionFailure，
#            长连接实测 20/20 全成功；本机 urllib 每张都新建连接才会撞上 25% 的 SSL EOF。
#   local  = 本机 127.0.0.1 图片服务（自带重试 + 缓存 + WebP→JPEG）。个别壳连不上 CDN 时改这档。
IMG_MODE = "direct"
IMG_CACHE = 128

# 播放是否改写清单（本站分片是裸相对名，标准 HLS 会按清单 URL 解析 → 默认不需要）。
# 只有 extend={"m3u8":"proxy"} 才打开，走 localProxy 绝对化重写。
USE_PROXY = False

# (category_id, 名称) —— 与 GET categories 完全一致（2026-11-08 实测 3 类）
CATS = [
    ("0183979e-f639-42be-921e-9b03f5f8df0a", "AI短剧"),
    ("72203b87-ebd8-45ef-b9d0-163ab538859b", "AI漫剧"),
    ("c140726b-0c62-4e64-a260-032854c71f40", "AI魔改"),
]

# ★ 站点真的只有这 3 个分类（2026-11-08 全站 724 条扫完确认，分布 668 / 15 / 41，
#   没有任何第 4 个 category_id，也没有 tag 维度——tag / tag_id / tags 参数一律 400）。
#   但接口支持**不带 category_id** 的全站列表（实测 724 条 / 37 页），
#   所以补一个「全部」入口，否则左侧只挂 3 项，看着像少了分类。
ALL_TID = "all"
ALL_NAME = "全部"

# sort 合法枚举（接口只认这四个，别的值直接 400）
# recommend 与 hot 首条重合 → 不放进筛选器，避免两个按钮一个结果
SORTS = [
    ("latest", "最新"),
    ("hot", "最热"),
    ("shuffle", "随机"),
]
_DEF_SORT = "latest"
_SORT_VALS = [x[0] for x in SORTS]

# 筛选组：key / name / value，选项 n / v（字段名一个都不能错）
FILTERS = [
    {
        "key": "srt",
        "name": "排序",
        "value": [{"n": n, "v": v} for v, n in SORTS],
    },
]

_LIMIT = 20
_TID_NAME = dict(CATS)
_NAME_TID = dict((v, k) for k, v in CATS)
_NAME_TID[ALL_NAME] = ALL_TID


# ======================================================================
# 二、内容脱敏（成人站全量档，固化；命中即丢弃该条目）
# ======================================================================
BLOCK_KW = [
    "幼女", "幼齿", "萝莉", "未成年", "小学生", "中学生", "儿童", "小孩子", "女童", "男童",
    "正太", "少男", "童装", "稚嫩", "学生妹", "幼态", "童颜", "萝莉控", "幼幼", "幼交",
    "强奸", "轮奸", "迷奸", "下药", "迷药", "迷晕", "昏迷", "捡尸", "偷拍", "偷窥",
    "针孔", "试衣间", "更衣室", "厕所偷", "迷魂", "催情", "春药", "听话水", "乖乖水",
    "非自愿", "强上", "强暴", "霸王硬上弓",
    "乱伦", "母子", "父女", "兄妹", "姐弟", "近亲",
    "兽交", "人兽", "动物交", "兽奸",
    "门事件", "艳照门", "艳照",
    "鸡巴", "肉棒", "阳具", "大屌", "龟头", "小穴", "骚穴", "肉缝", "后穴",
    "淫水", "爱液", "精液", "白浊", "奶子", "巨乳", "爆乳", "阴蒂",
    "口交", "肛交", "深喉", "口活", "口爆", "内射", "颜射", "射精",
    "潮吹", "打飞机", "自慰", "抽插", "乳交", "足交", "群交", "轮交",
    "发骚", "发浪", "浪叫", "娇喘",
    "跳蛋", "按摩棒", "假阳具", "肛塞", "情趣用品", "无码", "里番",
    "福利姬", "母狗", "性奴", "成人综艺", "鬼父", "淫母", "嫂子诱惑", "小姨子",
    "爷孙", "臀后", "拳交", "凌辱", "调教", "媚黑", "骚逼", "人妖", "伪娘",
    "禁漫", "性爱", "淫娃", "淫欲", "情趣", "骚播",
]
BLOCK_VAR = [
    "骨科", "近亲相奸", "母子乱", "父女乱", "兄妹乱", "姐弟乱",
    "视奸", "迷魂水", "苍蝇水", "厕所偷窥", "走光偷拍",
    "牛头人", "绿帽", "群p", "多p", "双飞",
    "几把", "牛子", "品玉", "舔穴", "观音坐莲", "毒龙钻",
    "制服诱惑", "原味内裤", "开档", "成人片", "成人影片", "成人视频", "av女优",
]

_ZW = "\u200b\u200c\u200d\ufeff\u2060\u00ad"
_SEP = "\u00b7\u2022.*-_=~|/\\+ \t\r\n\u3000\u3001\u3002"
_ZW_RE = re.compile("[" + _ZW + "]")
_SEP_RE = re.compile("[" + re.escape(_SEP) + "]")
_ASCII_RE = re.compile(r"(?<![a-z0-9])(?:j8|jb|3p|4p|5p|ntr|lolita|loli)(?![a-z0-9])")


def _norm(t):
    try:
        import unicodedata
        t = unicodedata.normalize("NFKC", str(t))
    except Exception:
        t = str(t)
    return _ZW_RE.sub("", t).lower()


def _blocked(text):
    if not text:
        return False
    raw = str(text)
    if _ZW_RE.search(raw):
        return True
    t = _norm(raw)
    sq = _SEP_RE.sub("", t)
    for k in BLOCK_KW:
        if k in t or k in sq:
            return True
    for k in BLOCK_VAR:
        if k in t or k in sq:
            return True
    if _ASCII_RE.search(t):
        return True
    return False


# ======================================================================
# 三、图片工具
# ======================================================================
def _img_mime(b):
    """按魔数判图片类型：CDN 给的 .webp 后缀可信，但仍以内容为准。"""
    if not b:
        return ""
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"GIF8":
        return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:2] == b"BM":
        return "image/bmp"
    return ""


def _webp2jpg(data):
    """WebP → JPEG：有 Pillow 才转，没有就原样吐 WebP（绝不因此丢图）。"""
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        try:
            im.seek(0)
        except Exception:
            pass
        im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, "JPEG", quality=88)
        got = out.getvalue()
        return got if got[:3] == b"\xff\xd8\xff" else None
    except Exception:
        return None


if _httpsrv is not None:
    class _ImgServer(_httpsrv.BaseHTTPRequestHandler):
        """本机封面服务：/pic/<md5>.jpg?u=<quote(原图)> → 源带 UA 取图后明文输出。"""

        spider = None
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            try:
                u = ""
                if "?" in self.path:
                    for kv in self.path.split("?", 1)[1].split("&"):
                        if kv.startswith("u="):
                            u = _unquote(kv[2:])
                            break
                got = _ImgServer.spider._img_bytes(u) if (u and _ImgServer.spider) else None
                if got:
                    img, mime = got
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(img)))
                    self.send_header("Cache-Control", "max-age=86400")
                    self.end_headers()
                    self.wfile.write(img)
                else:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
            except Exception:
                try:
                    self.close_connection = True
                except Exception:
                    pass

        def log_message(self, *args):
            pass
else:
    _ImgServer = None


def _new_iid():
    """install_id 契约：^[A-Za-z0-9_-]{16,64}$。同一进程内固定，游客身份可复用。"""
    try:
        import uuid
        return "czd" + uuid.uuid4().hex[:20]
    except Exception:
        pass
    try:
        import os
        return "czd" + os.urandom(10).hex()
    except Exception:
        return "czd" + "0" * 20


_IID = _new_iid()


# ======================================================================
# 四、Spider
# ======================================================================
class Spider(_BaseSpider):

    def __init__(self, *args, **kwargs):
        # ★ 收 *args/**kwargs：壳会用 Spider('x') / Spider(1,2,3) 反射实例化
        # ★ 壳基类可能在 __init__ 里准备状态；完全不复用 → 基类字段全缺（2026-11-02 QQ音乐 实测）
        try:
            _BaseSpider.__init__(self)
        except Exception:
            pass
        self.site = SITE
        self.api = API
        self.name = NAME
        self.header = {
            "User-Agent": UA,
            "Referer": self.site + "/",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "application/json, text/plain, */*",
        }
        # 少数壳读复数名 headers，留别名（同一个 dict）
        self.headers = self.header
        # ★ 壳内置 requests 常是残缺版（缺 ssl），裸调 Session() 会抛 → __init__ 崩 → 整源加载失败
        try:
            _sess = _requests.Session() if _requests is not None else None
            if _sess is not None:
                # 不继承系统代理环境变量（HTTP_PROXY / HTTPS_PROXY）
                try:
                    _sess.trust_env = False
                except Exception:
                    pass
        except Exception:
            _sess = None
        self.s = self.session = self.sess = _sess

        # ---- 骨架结构位（JSON 站：路径模板代替 HTML 选择器）----
        self.cat_scope = None
        self.cat_href_re = None
        self.list_scope = None
        self.cat_tpl = "dramas?category_id={tid}&page={pg}&sort={srt}"
        self.detail_tpl = "dramas/{id}"
        self.play_tpl = "playback/episodes/{id}"
        self.eps_tpl = "dramas/{id}/episodes?page={pg}"
        self.search_tpl = "dramas?q={key}&page={pg}"
        self.page_mode = "query"

        # ---- 筛选器（2026-10-24 起必备）----
        # filter_groups: [{"key","name","value":[{"n":显示名,"v":值}]}]
        # filter_keys  : 白名单，只允许这些 key 拼进 URL（防注入 / 防壳传脏值）
        # ★ 本站对未知参数直接 400，白名单是硬要求，不是可选项
        self.filter_groups = FILTERS
        self.filter_keys = ["srt"]

        self.use_proxy = USE_PROXY
        self.img_mode = IMG_MODE

        # ---- 运行态（OK影视 只做 Spider()，不调 init，所以必须全在 __init__ 里初始化）----
        self._extend = {}
        self._home = None
        self._iid = _IID
        self._tok = ""
        self._tok_exp = 0.0
        self._srv = None
        self._srv_port = 0
        self._imgc = {}
        self._cache = {}
        self._op = None

    # ------------------------------------------------------------------ 契约
    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        if not url:
            return False
        u = str(url).lower()
        return u.endswith((".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".avi")) or "m3u8" in u

    def action(self, action):
        return ""            # ★ 返 {} 部分壳按字符串用会崩

    def destroy(self):
        try:
            if self._srv is not None:
                self._srv.shutdown()
        except Exception:
            pass
        self._srv = None
        self._srv_port = 0
        return None

    def init(self, extend=""):
        """零网络：只解析 extend，不取 token、不发请求。"""
        self._extend = {}
        if isinstance(extend, dict):
            self._extend = extend
        elif isinstance(extend, str) and extend.strip():
            try:
                e = json.loads(extend)
                if isinstance(e, dict):
                    self._extend = e
            except Exception:
                pass
        m = str(self._extend.get("m3u8") or "").strip().lower()
        if m in ("proxy", "local", "1", "true", "on"):
            self.use_proxy = True
        elif m in ("direct", "off", "0", "false"):
            self.use_proxy = False
        im = str(self._extend.get("img") or "").strip().lower()
        if im in ("local", "proxy", "1", "true", "on"):
            self.img_mode = "local"
        elif im in ("direct", "off", "0", "false"):
            self.img_mode = "direct"
        return self          # ★ OK影视 要求：返回 None 会把 spider 置空 → 整源加载不出来

    # ------------------------------------------------------------------ 网络层
    def _now(self):
        try:
            import time
            return time.time()
        except Exception:
            return 0.0

    def _run_to(self, fn, budget):
        """线程 + join 硬超时：壳的 requests 会无视 timeout，必须自己掐表。"""
        if _th is None:
            try:
                return fn()
            except Exception:
                return None
        box = {}

        def _w():
            try:
                box["v"] = fn()
            except Exception:
                box["v"] = None

        try:
            t = _th.Thread(target=_w)
            t.daemon = True
            t.start()
            t.join(budget)
        except Exception:
            try:
                return fn()
            except Exception:
                return None
        return box.get("v")

    def _opener(self):
        if self._op is not None:
            return self._op
        try:
            import urllib.request
            handlers = [urllib.request.ProxyHandler({})]
            try:
                import ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                handlers.append(urllib.request.HTTPSHandler(context=ctx))
            except Exception:
                pass
            self._op = urllib.request.build_opener(*handlers)
        except Exception:
            self._op = None
        return self._op

    def _http(self, url, data=None, hdr=None, timeout=10):
        """返回 (status, bytes)；失败 (0, b"")。直连，不走系统代理。"""
        h = {"User-Agent": UA}
        if hdr:
            h.update(hdr)
        if _requests is not None:
            def _call():
                sess = self.s
                method = "POST" if data is not None else "GET"
                if sess is not None:
                    r = sess.request(method, url, data=data, headers=h,
                                     timeout=timeout, verify=False)
                else:
                    r = _requests.request(method, url, data=data, headers=h,
                                          timeout=timeout, verify=False)
                return getattr(r, "status_code", 0), (r.content or b"")

            got = self._run_to(_call, max(3, min(timeout, 6)))
            if got and got[0]:
                return got
        try:
            import urllib.request
            op = self._opener()
            req = urllib.request.Request(url, data=data, headers=h)
            if op is not None:
                r = op.open(req, timeout=timeout)
            else:
                r = urllib.request.urlopen(req, timeout=timeout)
            return r.status, r.read()
        except Exception as e:
            code = getattr(e, "code", 0) or 0
            body = b""
            try:
                body = e.read()
            except Exception:
                body = b""
            return code, body

    # ---- 鉴权 ----
    def _token(self):
        """游客 token，900 秒有效；过期重新 guest（不调 refresh，它会作废旧 token）。"""
        if self._tok and self._now() < self._tok_exp:
            return self._tok
        d = self._api("auth/guest",
                      body={"install_id": self._iid, "platform": "android"},
                      auth=False, timeout=10)
        if not d:
            return ""
        self._tok = str(d.get("access_token") or "")
        try:
            exp = int(d.get("access_expires_in") or 900)
        except Exception:
            exp = 900
        self._tok_exp = self._now() + max(60, exp - 60)
        return self._tok

    def _api(self, path, body=None, auth=True, timeout=10):
        """GET/POST 一个 JSON 接口，返回 data 段；任何异常一律 None。"""
        url = self.api + "/" + str(path).lstrip("/")
        hdr = {}
        if auth:
            t = self._token()
            if not t:
                return None
            hdr["Authorization"] = "Bearer " + t
        data = None
        if body is not None:
            try:
                data = json.dumps(body).encode("utf-8")
            except Exception:
                return None
            hdr["Content-Type"] = "application/json; charset=utf-8"
        st, raw = self._http(url, data, hdr, timeout)
        if st == 0 and not raw:
            st, raw = self._http(url, data, hdr, timeout)
        if st == 401 and auth:
            self._tok = ""
            self._tok_exp = 0.0
            t = self._token()
            if not t:
                return None
            hdr["Authorization"] = "Bearer " + t
            st, raw = self._http(url, data, hdr, timeout)
        if st != 200 or not raw:
            return None
        try:
            j = json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            return None
        if not isinstance(j, dict) or j.get("code") != 0:
            return None
        return j.get("data")

    def _get_bytes(self, url, timeout=10, retry=3, accept="*/*"):
        """取原始字节：CDN 握手有约 25% 抖动（SSL EOF），必须重试。"""
        if not url:
            return b""
        hdr = {"Accept": accept}
        for i in range(max(1, retry)):
            st, raw = self._http(url, None, hdr, timeout)
            if st == 200 and raw:
                return raw
            if i + 1 < max(1, retry):
                try:
                    import time
                    time.sleep(0.25)
                except Exception:
                    pass
        return b""

    def _get_text(self, url, timeout=10, retry=3):
        raw = self._get_bytes(url, timeout, retry,
                              accept="application/vnd.apple.mpegurl,*/*")
        if not raw:
            return ""
        try:
            return raw.decode("utf-8", "ignore")
        except Exception:
            return ""

    # ------------------------------------------------------------------ 封面
    def _ensure_srv(self):
        """懒启动 127.0.0.1 图片服务，返回端口；起不来返回 0（调用方降级直连）。"""
        if self._srv_port:
            return self._srv_port
        if _ImgServer is None or _sock is None or _th is None:
            self._srv_port = 0
            return 0
        try:
            _ImgServer.spider = self
            _sock.ThreadingTCPServer.allow_reuse_address = True
            httpd = _sock.ThreadingTCPServer(("127.0.0.1", 0), _ImgServer)
            httpd.daemon_threads = True
            t = _th.Thread(target=httpd.serve_forever)
            t.daemon = True
            t.start()
            self._srv = httpd
            self._srv_port = httpd.server_address[1]
        except Exception:
            self._srv = None
            self._srv_port = 0
        return self._srv_port

    def _img_bytes(self, url):
        """取封面字节：重试 + 缓存；WebP 能转就转 JPEG。"""
        try:
            u = str(url or "").strip()
            if not u.startswith("http"):
                return None
            ck = hashlib.md5(u.encode("utf-8", "ignore")).hexdigest()
            hit = self._imgc.get(ck)
            if hit:
                return hit
            data = self._get_bytes(u, timeout=10, retry=4, accept="image/*,*/*")
            if not data:
                return None
            mime = _img_mime(data)
            if not mime:
                return None
            if mime == "image/webp":
                jpg = _webp2jpg(data)
                if jpg:
                    data, mime = jpg, "image/jpeg"
            if len(self._imgc) >= IMG_CACHE:
                self._imgc.clear()
            self._imgc[ck] = (data, mime)
            return (data, mime)
        except Exception:
            return None

    def _pic(self, src):
        """封面：默认直连（壳有连接池）；img_mode=local 时转本机图片服务。"""
        u = str(src or "").strip()
        if not u:
            return ""
        if u.startswith("//"):
            u = "https:" + u
        if not u.startswith("http"):
            return u
        if self.img_mode == "local":
            port = self._ensure_srv()
            if port:
                key = hashlib.md5(u.encode("utf-8", "ignore")).hexdigest()[:16]
                return "http://127.0.0.1:%d/pic/%s.jpg?u=%s" % (
                    port, key, _quote(u, safe=""))
        return u

    # ------------------------------------------------------------------ 工具
    def _tid(self, tid):
        t = str(tid or "").strip()
        if t == ALL_TID:
            return ALL_TID
        if t in _TID_NAME:
            return t
        if t in _NAME_TID:
            return _NAME_TID[t]
        return t

    def _flt(self, extend):
        """从 extend 取筛选值。key 与 value 双重白名单，脏值直接丢弃。

        ★ 本站对未知参数一律 400，所以这里绝不能放任何未白名单的值过去。
        """
        out = {}
        if not isinstance(extend, dict) or not self.filter_keys:
            return out
        allow = {}
        for g in (self.filter_groups or []):
            try:
                allow[str(g.get("key"))] = set(str(o.get("v")) for o in (g.get("value") or []))
            except Exception:
                pass
        for k in self.filter_keys:
            v = str(extend.get(k) or "").strip()
            if not v:
                continue
            vs = allow.get(k)
            if vs and v not in vs:
                continue
            out[k] = v
        return out

    def _srt_of(self, ext):
        v = str((ext or {}).get("srt") or "").strip().lower()
        return v if v in _SORT_VALS else _DEF_SORT

    def _pack(self, vods, pg, pc, total=0):
        pc = max(1, int(pc or 1))
        try:
            tot = int(total or 0)
        except Exception:
            tot = 0
        if tot <= 0:
            # 接口没给 total 时按页推算；真没结果就老实报 0，别虚报一页
            tot = pc * _LIMIT if vods else 0
        return {
            "list": vods,
            "page": int(pg or 1),
            "pagecount": pc,
            "limit": _LIMIT,
            "total": tot,
        }

    def _cached(self, key, fn):
        """小缓存（上限 64），避免壳翻回上一页时重复打接口。"""
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        got = fn()
        try:
            if len(self._cache) >= 64:
                self._cache.clear()
            self._cache[key] = got
        except Exception:
            pass
        return got

    # ------------------------------------------------------------------ 解析
    def _vod(self, d):
        """drama JSON → 壳的 vod dict；命中脱敏词返回 None。"""
        if not isinstance(d, dict):
            return None
        title = str(d.get("title") or "").strip()
        desc = str(d.get("description") or "").strip()
        tags = ",".join([str(t.get("name") or "") for t in (d.get("tags") or [])
                         if isinstance(t, dict)])
        cat = d.get("category") or {}
        area = str(cat.get("name") or "").strip() if isinstance(cat, dict) else ""
        if _blocked(title) or _blocked(desc) or _blocked(tags):
            return None
        vid = str(d.get("id") or "").strip()
        if not vid:
            return None
        try:
            cnt = int(d.get("published_episode_count") or d.get("total_episodes") or 0)
        except Exception:
            cnt = 0
        status = str(d.get("serial_status") or "").strip()
        remarks = ("%d集" % cnt) if cnt > 0 else ("连载中" if status == "ongoing" else "")
        year = ""
        up = str(d.get("updated_at") or "")
        if len(up) >= 4 and up[:4].isdigit():
            year = up[:4]
        return {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": self._pic(d.get("cover_url") or d.get("cover_thumb_url") or ""),
            "vod_remarks": remarks,
            "vod_year": year,
            "vod_area": area,
            "vod_actor": tags,
            "vod_content": desc,
        }

    def _items(self, data):
        """JSON data 段 → vod 列表（骨架 _items 的 JSON 版）。"""
        out = []
        seen = set()
        if not isinstance(data, dict):
            return out
        for it in data.get("items") or []:
            d = it.get("drama") if isinstance(it, dict) and "drama" in it else it
            v = self._vod(d)
            if v and v["vod_id"] not in seen:
                seen.add(v["vod_id"])
                out.append(v)
        return out

    def _page_meta(self, data, pg):
        """从 data 的 total / page_size 推 pagecount。"""
        try:
            total = int((data or {}).get("total") or 0)
        except Exception:
            total = 0
        try:
            size = int((data or {}).get("page_size") or _LIMIT) or _LIMIT
        except Exception:
            size = _LIMIT
        pc = max(1, (total + size - 1) // size) if total > 0 else max(1, pg)
        return total, pc

    # ------------------------------------------------------------------ 分类
    def _cats(self):
        """分类：优先接口实时取（缓存），失败退回内置 CATS。"""
        if self._home is not None:
            return self._home
        out = []
        d = self._api("categories", timeout=10)
        for it in ((d or {}).get("items") or []):
            if not isinstance(it, dict):
                continue
            tid = str(it.get("id") or "").strip()
            nm = str(it.get("name") or "").strip()
            if tid and nm:
                out.append({"type_id": tid, "type_name": nm})
        if not out:
            out = [{"type_id": k, "type_name": v} for k, v in CATS]
        # 「全部」置顶：不带 category_id 的全站列表（724 条）
        out = [{"type_id": ALL_TID, "type_name": ALL_NAME}] + out
        self._home = out
        return out

    def _cat_url(self, tid, pg, ext=None):
        """分类页 API 路径（骨架 _cat_url 的 JSON 版）。"""
        ext = ext or {}
        srt = self._srt_of(ext)
        if str(tid) == ALL_TID:
            # 不带 category_id = 全站列表；实测 724 条 / 37 页，带 sort 也生效
            return "dramas?page=%d&sort=%s" % (int(pg), srt)
        return self.cat_tpl.format(tid=_quote(str(tid), safe=""), pg=int(pg), srt=srt)

    # ------------------------------------------------------------------ 首页
    def _feed(self):
        """首页流：推荐流 10 条 + 每个分类第 1 页，去重合并。

        ★ 不要用 recommend/next 凑量：实测它一次只回 1 条（不是分页接口）。
        """
        out = []
        seen = set()

        def add(vods):
            for v in vods:
                if v["vod_id"] not in seen:
                    seen.add(v["vod_id"])
                    out.append(v)

        try:
            add(self._items(self._api("recommend/feed", timeout=10)))
        except Exception:
            pass
        for c in self._cats():
            if c["type_id"] == ALL_TID:
                continue     # 「全部」与各分类高度重合，首页不重复拉
            try:
                add(self._items(self._api(
                    self._cat_url(c["type_id"], 1, None), timeout=10)))
            except Exception:
                pass
        return out

    def homeContent(self, filter=None, *args, **kwargs):
        cats = self._cats()
        out = {"class": cats, "list": []}
        if self.filter_groups and cats:
            # 每个分类都挂同一套筛选器
            out["filters"] = dict((c["type_id"], self.filter_groups) for c in cats)
        try:
            out["list"] = self._feed()
        except Exception:
            pass
        return out

    def homeVideoContent(self, *args, **kwargs):
        try:
            return {"list": self._feed()}
        except Exception:
            return {"list": []}

    # ------------------------------------------------------------------ 分类页
    def categoryContent(self, tid, pg=1, filter=None, extend=None, *args, **kwargs):
        t = self._tid(tid)
        # 优先 extend（多数壳走这里）；个别壳把值塞在 filter 里，一并兼容
        ext = self._flt(extend) or self._flt(filter)
        srt = self._srt_of(ext)
        try:
            p = max(1, int(float(str(pg or 1).strip() or 1)))
        except Exception:
            p = 1
        # ★ 缓存 key 必须带筛选值，否则换排序会串结果
        ck = "%s|%s|%s" % (t, srt, p)

        def _load():
            d = self._api(self._cat_url(t, p, ext), timeout=10)
            if not d and srt != _DEF_SORT:
                # 排序值被站点拒（400）→ 回落默认排序，绝不给空页
                d = self._api(self.cat_tpl.format(tid=_quote(t, safe=""),
                                                  pg=p, srt=_DEF_SORT), timeout=10)
            if not d:
                return self._pack([], p, 1)
            vods = self._items(d)
            total, pc = self._page_meta(d, p)
            if p > pc:
                return self._pack([], p, pc, total)
            return self._pack(vods, p, pc, total)

        try:
            return self._cached(ck, _load)
        except Exception:
            return self._pack([], p, 1)

    # ------------------------------------------------------------------ 详情
    def _episodes(self, vid):
        """剧集列表（20/页，按集号升序）。"""
        out = []
        page = 1
        while page <= 20:
            d = self._api(self.eps_tpl.format(id=vid, pg=page), timeout=10)
            if not d:
                break
            items = d.get("items") or []
            out.extend([x for x in items if isinstance(x, dict)])
            try:
                total = int(d.get("total") or 0)
                size = int(d.get("page_size") or _LIMIT) or _LIMIT
            except Exception:
                total, size = 0, _LIMIT
            if not items or (total and len(out) >= total) or (not total and len(items) < size):
                break
            page += 1
        try:
            out.sort(key=lambda x: int(x.get("episode_number") or 0))
        except Exception:
            pass
        return out

    def detailContent(self, ids, *args, **kwargs):
        # ★ 收 *args/**kwargs：壳多传一个位置参就 TypeError
        try:
            vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        except Exception:
            vid = str(ids)
        m = re.search(r"[0-9a-fA-F-]{36}", vid)
        if m:
            vid = m.group(0)
        if not vid:
            return {"list": []}
        try:
            d = self._api(self.detail_tpl.format(id=vid), timeout=10)
            if not d:
                return {"list": []}
            v = self._vod(d)
            if v is None:
                return {"list": []}
            eps = self._episodes(vid)
            plays = []
            for i, e in enumerate(eps):
                n = e.get("episode_number") or (i + 1)
                eid = str(e.get("id") or "").strip()
                if eid:
                    plays.append("第%s集$%s" % (n, eid))
            if not plays:
                fe = str(d.get("first_episode_id") or "").strip()
                if fe:
                    plays.append("第1集$%s" % fe)
            # ★ 抓不到集数就留空，绝不编造线路
            v["vod_play_from"] = NAME if plays else ""
            v["vod_play_url"] = "#".join(plays)
            return {"list": [v]}
        except Exception:
            return {"list": []}

    # ------------------------------------------------------------------ 搜索
    def searchContent(self, key, quick=False, pg="1", *args, **kwargs):
        kw = str(key or "").strip()
        if not kw:
            # 空关键词必须不发请求直接返空（否则拉全站垃圾）
            return {"list": [], "page": 1, "pagecount": 1, "limit": _LIMIT, "total": 0}
        if " " in kw:
            kw = kw.split()[0]
        if len(kw) > 100:
            kw = kw[:100]
        try:
            p = max(1, int(pg or 1))
        except Exception:
            p = 1
        ck = "s|%s|%s" % (kw, p)

        def _load():
            d = self._api(self.search_tpl.format(key=_quote(kw, safe=""), pg=p), timeout=10)
            if not d:
                return {"list": [], "page": p, "pagecount": 1, "limit": _LIMIT, "total": 0}
            vods = self._items(d)
            total, pc = self._page_meta(d, p)
            if p > pc:
                return {"list": [], "page": p, "pagecount": pc, "limit": _LIMIT, "total": total}
            return {"list": vods, "page": p, "pagecount": pc, "limit": _LIMIT,
                    "total": total or (pc * _LIMIT if vods else 0)}

        try:
            return self._cached(ck, _load)
        except Exception:
            return {"list": [], "page": p, "pagecount": 1, "limit": _LIMIT, "total": 0}

    # ------------------------------------------------------------------ 播放
    def _needs_proxy(self, txt):
        """清单里出现非 http 开头的裸 URI（分片 / key / map）→ 需要源端绝对化。"""
        if not txt or "#EXTM3U" not in txt:
            return False
        for line in txt.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("#"):
                if 'URI="' in s:
                    mm = re.search(r'URI="([^"]+)"', s)
                    if mm and not mm.group(1).lower().startswith("http"):
                        return True
                continue
            if not s.lower().startswith("http"):
                return True
        return False

    def _rewrite(self, txt, base):
        """把相对分片/密钥绝对化：基准是清单自身 URL（不是站点根）。"""
        out = []
        for line in txt.splitlines():
            s = line.strip()
            if not s:
                out.append(line)
                continue
            if s.startswith("#"):
                if 'URI="' in s:
                    def _rep(mm):
                        return 'URI="%s"' % _urljoin(base, mm.group(1))
                    s = re.sub(r'URI="([^"]+)"', _rep, s)
                out.append(s)
                continue
            out.append(_urljoin(base, s))
        return "\n".join(out) + "\n"

    def _play_hdr(self):
        # ★ 播放层 header 只给 UA（带 Referer / Accept 会被 CDN 拒）
        return {"User-Agent": UA}

    def playerContent(self, flag, ids, vipFlags=None, *args, **kwargs):
        hdr = self._play_hdr()
        fail = {"parse": 0, "url": "", "header": hdr}
        try:
            u = str(ids or "").strip()
            # 壳可能把整条「第1集$xxxx」原样传进来
            if "$" in u:
                u = u.split("$")[-1].strip()
            if not u:
                return fail
            if u.lower().startswith("http"):
                # 已是直链：需要时才探测一次清单，默认不探测（省一个请求）
                if self.use_proxy:
                    txt = self._get_text(u, timeout=10, retry=2)
                    if txt and self._needs_proxy(txt):
                        return {"parse": 0,
                                "url": "proxy" + "://do=m3u8&url=" + _quote(u, safe=""),
                                "header": hdr}
                return {"parse": 0, "url": u, "header": hdr}
            # episode_id → 现取签名播放地址（20 分钟有效）
            d = self._api(self.play_tpl.format(id=u), timeout=10)
            if not d:
                return fail
            purl = str(d.get("playback_url") or "").strip()
            if not purl:
                return fail
            # ★ 默认直连：分片是裸相对名，标准 HLS 会以清单自身 URL 为基准解析（实测可播）
            if self.use_proxy:
                return {"parse": 0,
                        "url": "proxy" + "://do=m3u8&url=" + _quote(purl, safe=""),
                        "header": hdr}
            return {"parse": 0, "url": purl, "header": hdr}
        except Exception:
            return fail

    # ------------------------------------------------------------------ 本地代理
    def _param_url(self, param):
        """从壳传来的 param 里抠出目标 URL（兼容 dict / proxy:// 前缀 / proxy?url=）。"""
        p = ""
        if isinstance(param, dict):
            p = str(param.get("url") or param.get("u") or "")
        else:
            p = str(param or "")
        if not p:
            return ""
        _px = "proxy" + "://"
        _pq = "proxy?url="
        if p.startswith(_px):
            p = p[len(_px):]
        elif p.startswith(_pq):
            p = p[len(_pq):]
        if p.startswith("?"):
            p = p[1:]
        if "url=" in p and not p.lower().startswith("http"):
            p = p.split("url=", 1)[1]
            if "&" in p:
                p = p.split("&", 1)[0]
        if "%" in p:
            p = _unquote(p)
        return p.strip()

    def localProxy(self, param=None, *args, **kwargs):
        try:
            u = self._param_url(param)
            if not u or not u.lower().startswith("http"):
                return [403, "text/plain", b"", None]
            raw = self._get_bytes(u, timeout=10, retry=3)
            if not raw:
                return [404, "text/plain", b"", None]
            # 内容像播放列表就重写一层（do=ts 也可能塞的是子清单）
            if raw[:7] == b"#EXTM3U" or b"#EXT-X-" in raw[:512]:
                txt = raw.decode("utf-8", "ignore")
                return [200, "application/vnd.apple.mpegurl", self._rewrite(txt, u), None]
            mime = _img_mime(raw)
            if mime:
                return [200, mime, raw, None]
            return [200, "application/octet-stream", raw, None]
        except Exception:
            return [403, "text/plain", b"", None]
