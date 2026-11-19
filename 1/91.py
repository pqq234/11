# -*- coding: utf-8 -*-
# ak29x31k (https://e388.ak29x31k.cc/) - TVBox py 源
# 结构实测（2026-10-27，浏览器只读实测）：
#   分类（只取视频类）：成人短剧 /duanju/、成人漫剧 /manju/、真人剧 /zhenrenju/、
#         成人视频 /shipin/；漫画 /manhua/、小说 /xiaoshuo/ 非视频未作分类
#   列表：整张 <a> 卡片，内含封面 img、下方 <h3> 标题；详情 /<分类>/<id>-<slug>/
#   封面注意：浏览器视图里 img 呈现为 blob: 会话地址，不能直接用；原始 HTML 里 img src
#         只是 1×1 透明占位图，真实封面在 data-src/data-fallback-src 里且是加密值，
#         经 JS 解密后才变 blob:；封面处理已在代码里实现：详情先取 og 图片，再取真图，
#         最后加密 data-src 走壳代理 9978 + localProxy AES 解密（密钥/向量现取，验魔数
#         才下发）；加密值本身不直接当图片地址。真站封面率仍需客户端实测（未验证）。
# 评审修订（2026-10-27，按评审建议全改，原文件未动）：
#   删从未被调用的自起本地服务与旧空桩，只留壳代理；详情无集号时先扫“第 N 集”文本
#   再默认第 1 集并标注未验证；播放兜底首候选补普通 GET 首段探活；搜索中文编码仍待实测。
#   列表接口（2026-10-27 空列表诊断实测）：首屏为服务端渲染，但分类列表另有片段接口
#         /api/list/fragment?scope=category&key=<分类>&sort=new&page=<页>，返回 HTML 片段（非 JSON），
#         带 X-Requested-With: fetch 请求头；分类列表先走该接口，空时再回落整页
#   分页：/<分类>/page/<页>/，第 1 页为基地址本身
#   详情：<h1> 标题，左侧大封面，资料含分类/状态/集数/热度/日期；标签 /biaoqian/<slug>/
#   播放：详情地址 + <集号>/，如 /duanju/<id>-<slug>/1/；选集区同形态
#   搜索：/search/<关键词>/，翻页 /search/<关键词>/<页>/；实测关键词被转小写，中文编码未验证
#   播放页（2026-10-27 播放页 view-source 实测）：初始视图只有封面 + 播放按钮、DOM 无直链，
#         但源码里 <script id="playInitialData" type="application/json"> 含 current.src（带签名 HLS 清单），
#         eps 含每集 videoId，另有 playbackEndpoint /videos/<id>/episodes/__EP__/playback（__EP__ 换集号）；
#         故 playerContent 先解析 playInitialData 的 current.src，取不到再调 playbackEndpoint 扫 m3u8，
#         最后才回落 parse=1 嗅探；签名有时效、每次播放现取
#   门禁：无年龄门、无登录墙、无验证码，登录/注册仅为可选入口
import re
import time
import ssl
import urllib.request
import urllib.parse
import html as html_mod
from http.cookiejar import CookieJar

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass


def _gf_mul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = ((a << 1) & 0xFF) ^ (0x1B if hi else 0)
        b >>= 1
    return p


def _build_sboxes():
    inv = [0] * 256
    for i in range(1, 256):
        for j in range(1, 256):
            if _gf_mul(i, j) == 1:
                inv[i] = j
                break

    def rotl8(x, n):
        return ((x << n) | (x >> (8 - n))) & 0xFF
    sbox = [0] * 256
    for i in range(256):
        a = inv[i]
        sbox[i] = (a ^ rotl8(a, 1) ^ rotl8(a, 2) ^ rotl8(a, 3) ^ rotl8(a, 4) ^ 0x63) & 0xFF
    inv_sbox = [0] * 256
    for i, v in enumerate(sbox):
        inv_sbox[v] = i
    return sbox, inv_sbox


_SBOX, _INV_SBOX = _build_sboxes()


def _expand_key(key):
    rcon = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)
    w = [0] * 44
    for i in range(4):
        w[i] = (key[4 * i] << 24) | (key[4 * i + 1] << 16) | (key[4 * i + 2] << 8) | key[4 * i + 3]
    for i in range(4, 44):
        t = w[i - 1]
        if i % 4 == 0:
            t = ((_SBOX[(t >> 16) & 0xFF] << 24) | (_SBOX[(t >> 8) & 0xFF] << 16) |
                 (_SBOX[t & 0xFF] << 8) | _SBOX[(t >> 24) & 0xFF]) ^ (rcon[i // 4 - 1] << 24)
        w[i] = w[i - 4] ^ t
    rk = []
    for r in range(11):
        kb = []
        for k in range(4):
            ww = w[r * 4 + k]
            kb += [(ww >> 24) & 0xFF, (ww >> 16) & 0xFF, (ww >> 8) & 0xFF, ww & 0xFF]
        rk.append(kb)
    return rk


def _aes_ecb_decrypt_pure(data, key):
    rk = _expand_key(key)
    out = []
    for off in range(0, len(data), 16):
        s = [data[off + i] ^ rk[10][i] for i in range(16)]
        for r in range(9, 0, -1):
            s = [s[0], s[13], s[10], s[7], s[4], s[1], s[14], s[11],
                 s[8], s[5], s[2], s[15], s[12], s[9], s[6], s[3]]
            s = [_INV_SBOX[x] for x in s]
            s = [s[i] ^ rk[r][i] for i in range(16)]
            o = [0] * 16
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c], s[4 * c + 1], s[4 * c + 2], s[4 * c + 3]
                o[4 * c] = _gf_mul(0x0E, a0) ^ _gf_mul(0x0B, a1) ^ _gf_mul(0x0D, a2) ^ _gf_mul(0x09, a3)
                o[4 * c + 1] = _gf_mul(0x09, a0) ^ _gf_mul(0x0E, a1) ^ _gf_mul(0x0B, a2) ^ _gf_mul(0x0D, a3)
                o[4 * c + 2] = _gf_mul(0x0D, a0) ^ _gf_mul(0x09, a1) ^ _gf_mul(0x0E, a2) ^ _gf_mul(0x0B, a3)
                o[4 * c + 3] = _gf_mul(0x0B, a0) ^ _gf_mul(0x0D, a1) ^ _gf_mul(0x09, a2) ^ _gf_mul(0x0E, a3)
            s = o
        s = [s[0], s[13], s[10], s[7], s[4], s[1], s[14], s[11],
             s[8], s[5], s[2], s[15], s[12], s[9], s[6], s[3]]
        s = [_INV_SBOX[x] for x in s]
        s = [s[i] ^ rk[0][i] for i in range(16)]
        out += s
    return bytes(bytearray(out))


def _aes_cbc_decrypt_pure(key, iv, data):
    out = bytearray()
    prev = list(iv)
    for off in range(0, len(data), 16):
        block = bytes(bytearray(data[off:off + 16]))
        dec = _aes_ecb_decrypt_pure(block, key)
        out += bytes(bytearray([dec[i] ^ prev[i] for i in range(16)]))
        prev = list(block)
    return bytes(out)




class Spider(BaseSpider):
    def __init__(self):
        self.site_url = "https://e388.ak29x31k.cc"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Referer": self.site_url + "/",
        }
        self._cj = CookieJar()
        self._last = 0.0

    def init(self, extend=""):
        pass

    def getName(self):
        return "ak29x31k"

    def _fetch(self, url, timeout=12, extra_headers=None):
        gap = time.time() - self._last
        if gap < 0.5:
            time.sleep(0.5 - gap)
        self._last = time.time()
        try:
            ctx = ssl._create_unverified_context()
        except Exception:
            ctx = None
        for attempt in range(2):
            try:
                headers = dict(self.headers)
                if extra_headers:
                    headers.update(extra_headers)
                if attempt == 1:
                    # 第二次重试：Referer 改为请求页本身的目录，避免片段接口因 Referer 不对而拒
                    headers["Referer"] = url.rsplit("/", 1)[0] + "/"
                req = urllib.request.Request(url, headers=headers)
                opener = urllib.request.build_opener(
                    urllib.request.HTTPSHandler(context=ctx),
                    urllib.request.HTTPCookieProcessor(self._cj))
                with opener.open(req, timeout=timeout) as resp:
                    raw = resp.read()
                    enc = (resp.headers.get("Content-Encoding", "") or "").lower()
                    if "gzip" in enc or raw[:2] == b"\x1f\x8b":
                        import gzip
                        raw = gzip.decompress(raw)
                    text = raw.decode("utf-8", errors="ignore")
                    if text and len(text) >= 500:
                        return text
                    if attempt == 1:
                        return text
            except Exception:
                if attempt == 1:
                    return ""
                continue
        return ""

    def _abs(self, path):
        if not path:
            return ""
        if path.startswith("http"):
            return path
        if path.startswith("//"):
            return "https:" + path
        return urllib.parse.urljoin(self.site_url + "/", path)

    @staticmethod
    def _clean(text):
        if not text:
            return ""
        return re.sub(r"<[^>]+>", "", html_mod.unescape(text)).strip()

    @staticmethod
    def _real_pic(tag):
        # 只认像真实图片地址的候选：http、/ 路径且带图片扩展名；加密的 data-src 值无扩展名，直接跳过
        # 注意：data-src 在这两站是加密图地址，带图片扩展名也不能直接当真图，
        # 必须走代理解密；所以真图只认 data-original/srcset/src，data-src 留给 _enc_pic
        for attr in ("data-original", "srcset", "src"):
            mm = re.search(r'%s\s*=\s*["\']([^"\']+)["\']' % attr, tag, re.I)
            if not mm:
                continue
            cand = mm.group(1).strip().split(",")[0].split()[0] if attr == "srcset" else mm.group(1).strip()
            if not cand or cand.startswith(("blob:", "data:")) or "placeholder" in cand.lower():
                continue
            if cand.startswith(("http://", "https://", "//", "/")) and re.search(
                    r"\.(?:jpg|jpeg|png|webp|gif)(?:\?|$)", cand, re.I):
                return cand
        return ""

    def _probe_media(self, url):
        # 普通 GET 读首段探活：m3u8 验 #EXTM3U，mp4 验 ftyp；禁用 HEAD/Range 判活。
        # 节流与 _fetch 一致（0.5 秒），避免探活本身触发限流。
        try:
            gap = time.time() - self._last
            if gap < 0.5:
                time.sleep(0.5 - gap)
            self._last = time.time()
            ctx = ssl._create_unverified_context()
        except Exception:
            ctx = None
        try:
            req = urllib.request.Request(url, headers=self.headers)
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ctx),
                urllib.request.HTTPCookieProcessor(self._cj))
            with opener.open(req, timeout=10) as resp:
                head = resp.read(4096)
            low = (url or "").lower()
            if ".m3u8" in low:
                return b"#EXTM3U" in head
            if ".mp4" in low:
                return b"ftyp" in head
            return False
        except Exception:
            return False

    def _parse_cards(self, html_data):
        cards, seen = [], set()
        if not html_data:
            return cards
        # 详情链接 /<分类>/<id>-<slug>/，单双引号、尾斜杠有无都认
        for m in re.finditer(r'''href=['"](?:https?://[^"'/]+)?(/(?:duanju|manju|zhenrenju|shipin)/\d+-[^"'/]+/?)['"]''', html_data, re.I):
            link = m.group(1)
            if not link.endswith("/"):
                link += "/"
            if link in seen:
                continue
            seen.add(link)
            # 标题：链接后 5000 字内最近的 h3，其次链接前 2000 字内的 h3，再次 img alt
            title = ""
            win_after = html_data[m.start():m.start() + 5000]
            hm = re.search(r"<h3[^>]*>(.*?)</h3>", win_after, re.S | re.I)
            if hm:
                title = self._clean(hm.group(1))
            if not title:
                win_before = html_data[max(0, m.start() - 2000):m.start()]
                hm = re.search(r"<h3[^>]*>(.*?)</h3>", win_before, re.S | re.I)
                if hm:
                    title = self._clean(hm.group(1))
            if not title:
                am = re.search(r'alt="([^"]+)"', win_after, re.I)
                if am:
                    title = self._clean(am.group(1))
            if not title:
                continue
            pic = ""
            im = re.search(r"<img[^>]+>", win_after, re.I)
            if im:
                pic = self._abs(self._real_pic(im.group(0)))
                if not pic:
                    enc = self._enc_pic(im.group(0))
                    if enc:
                        pic = self._proxy_pic(self._abs(enc))
            if not pic:
                enc = self._enc_pic_any(win_after[:5000])
                if enc:
                    pic = self._proxy_pic(self._abs(enc))
            cards.append({"vod_id": link, "vod_name": title,
                          "vod_pic": pic, "vod_remarks": ""})
        return cards

    def _category_cards(self, base, pg):
        # 先走片段接口，空时回落整页
        key = base.strip("/")
        frag_url = ("%s/api/list/fragment?scope=category&key=%s&sort=new&page=%d"
                    % (self.site_url, key, pg))
        frag = self._fetch(frag_url, extra_headers={
            "X-Requested-With": "fetch",
            "Referer": self._list_url(base, pg)})
        cards = self._parse_cards(frag)
        if cards:
            return cards
        return self._parse_cards(self._fetch(self._list_url(base, pg)))

    def _list_url(self, base, pg):
        base = base if base.endswith("/") else base + "/"
        if pg <= 1:
            return self.site_url + base
        return self.site_url + base + "page/%d/" % pg

    def homeContent(self, filter):
        cats = [
            {"type_id": "/duanju/", "type_name": "成人短剧"},
            {"type_id": "/manju/", "type_name": "成人漫剧"},
            {"type_id": "/zhenrenju/", "type_name": "真人剧"},
            {"type_id": "/shipin/", "type_name": "成人视频"},
        ]
        return {"class": cats, "filters": {}}

    def homeVideoContent(self):
        return {"list": self._category_cards("/duanju/", 1)[:20]}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        base = str(tid or "/duanju/")
        cards = self._category_cards(base, pg)
        return {"list": cards, "page": pg,
                "pagecount": pg + 1 if cards else pg,
                "limit": len(cards), "total": 0}

    def detailContent(self, ids):
        vid = str(ids[0]).strip() if ids else ""
        shell = {"vod_id": vid, "vod_name": "", "vod_pic": "",
                 "vod_remarks": "", "vod_play_from": "", "vod_play_url": ""}
        if not vid:
            return {"list": [shell]}
        url = vid if vid.startswith("http") else self._abs(vid)
        html_data = self._fetch(url)
        if not html_data:
            return {"list": [shell]}
        tm = re.search(r"<h1[^>]*>(.*?)</h1>", html_data, re.S | re.I)
        if tm:
            shell["vod_name"] = self._clean(tm.group(1))
        # 封面优先：og:image / twitter:image 常为真实图片地址（带 auth 参数），先取它
        om = re.search(r'<meta[^>]+(?:property="og:image"|name="twitter:image")[^>]+content="([^"]+)"', html_data, re.I)
        if not om:
            om = re.search(r'<meta[^>]+content="([^"]+)"[^>]+(?:property="og:image"|name="twitter:image")', html_data, re.I)
        if om and re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", om.group(1), re.I):
            shell["vod_pic"] = self._abs(om.group(1))
        # 封面：og:image 未取到时再看详情大图，跳过 blob:
        if not shell["vod_pic"]:
            for im in re.finditer(r"<img[^>]+>", html_data, re.I):
                pic = self._real_pic(im.group(0))
                if pic:
                    shell["vod_pic"] = self._abs(pic)
                    break
        # 详情封面也可能在加密 data-src 上：真图取不到时走 9978 代理
        if not shell["vod_pic"]:
            enc = self._enc_pic_any(html_data)
            if enc:
                shell["vod_pic"] = self._proxy_pic(self._abs(enc))
        # 选集：详情地址 + <集号>/，按集号排序去重
        base = url if url.endswith("/") else url + "/"
        eps = sorted({int(x) for x in re.findall(
            re.escape(base) + r"(\d+)/", html_data)})
        if not eps:
            # 详情页地址里没扫到集号时，再扫“第 N 集”文本；仍无才默认第 1 集。
            eps = sorted({int(x) for x in re.findall(r"第\s*(\d+)\s*集", html_data)})
        if eps and 1 not in eps:
            # 详情本身即第 1 集的入口，有其他集时第 1 集应存在，补上，避免只剩 2、3 集。
            eps = [1] + eps
        if not eps:
            # 未验证：默认仅第 1 集可能是单集，也可能是选集区未解析，待实测。
            eps = [1]
        shell["vod_play_from"] = "在线播放"
        shell["vod_play_url"] = "#".join(
            "第%d集$%s%d/" % (n, base, n) for n in eps)
        return {"list": [shell]}

    def playerContent(self, flag, id, vipFlags):
        raw = str(id or "").strip()
        if "$" in raw:
            raw = raw.rsplit("$", 1)[-1].strip()
        header = {"User-Agent": self.headers["User-Agent"],
                  "Referer": self.site_url + "/"}
        if raw.lower().startswith("http") and (".m3u8" in raw.lower() or ".mp4" in raw.lower()):
            return {"parse": 0, "playUrl": "", "url": raw, "header": header}
        url = raw if raw.startswith("http") else self._abs(raw)
        html_data = self._fetch(url)
        # 播放页源码 playInitialData：current.src 即本集 HLS
        try:
            import json as _json
            jm = re.search(r'<script id="playInitialData"[^>]*>(.*?)</script>', html_data, re.S | re.I)
            if jm:
                jdata = _json.loads(jm.group(1))
                cur = jdata.get("current") or {}
                src = cur.get("src", "") if isinstance(cur, dict) else ""
                if src and ".m3u8" in src:
                    return {"parse": 0, "playUrl": "", "url": src, "header": header}
                # 备用：playbackEndpoint 换集号后取
                ep_m = re.search(r"/(\d+)/?$", url.rstrip("/"))
                endpoint = jdata.get("playbackEndpoint", "") if isinstance(jdata, dict) else ""
                if endpoint and ep_m:
                    ep_url = endpoint.replace("__EP__", ep_m.group(1))
                    ep_text = self._fetch(ep_url, extra_headers={"Referer": url})
                    mm = re.search(r'"(https?://[^"]+\.m3u8[^"]*)"', ep_text)
                    if mm:
                        return {"parse": 0, "playUrl": "", "url": mm.group(1).replace("\\/", "/"),
                                "header": header}
        except Exception:
            pass
        cands = []
        for pat in (r'<source[^>]+src="([^"]+)"', r'<video[^>]+src="([^"]+)"'):
            cands += re.findall(pat, html_data, re.I)
        cands += re.findall(r'"(https?://[^"]+\.(?:m3u8|mp4)[^"]*)"', html_data, re.I)
        cands += re.findall(r"'(https?://[^']+\.(?:m3u8|mp4)[^']*)'", html_data, re.I)
        seen = set()
        for cand in cands:
            cand = cand.strip().replace("\\/", "/")
            low = cand.lower()
            if cand in seen or any(k in low for k in ("preview", "sample", "trailer", "thumb")):
                continue
            seen.add(cand)
            cand_url = self._abs(cand)
            # 兜底候选必须探活通过才 parse=0；验不过继续下一个，全灭回 parse=1
            if self._probe_media(cand_url):
                return {"parse": 0, "playUrl": "", "url": cand_url, "header": header}
        # 初始视图无直链：交壳内嗅探（播放直链位置未验证）
        return {"parse": 1, "playUrl": "", "url": url, "header": header}

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        # 搜索词转小写为本站行为；中文编码（urllib quote，utf-8）仍待实测，勿当已验证。
        kw = urllib.parse.quote(str(key).lower())
        if pg <= 1:
            url = "%s/search/%s/" % (self.site_url, kw)
        else:
            url = "%s/search/%s/%d/" % (self.site_url, kw, pg)
        html_data = self._fetch(url)
        cards = self._parse_cards(html_data)
        return {"list": cards, "page": pg,
                "pagecount": pg + 1 if cards else pg,
                "limit": len(cards), "total": 0}

    def isVideoFormat(self, url):
        u = (url or "").lower()
        return u.endswith(".m3u8") or ".m3u8?" in u or u.endswith(".mp4") or ".mp4?" in u


    def _cover_cfg(self, force=False):
        import time as _time
        now = _time.time()
        if not force and getattr(self, "_cfg_cache", None) and now - self._cfg_cache[0] < 3600:
            return self._cfg_cache[1]
        cfg = {"key": b"", "iv": b"", "headers": {}}
        try:
            cdn = self._fetch(self.site_url + "/cdn-config.js")
            def _fld(txt, name):
                m = re.search(r"(?<![A-Za-z0-9_-])" + name + r"[\"\']?\s*[:=]\s*[\"\']([^\"\']+)[\"\']", txt or "")
                return m.group(1) if m else ""
            hname = _fld(cdn, "imgAuthKey")
            hval = _fld(cdn, "imgAuthValue")
            app = _fld(cdn, "app")
            hdrs = {}
            if hname and hval:
                hdrs[hname] = hval
            if app:
                hdrs["x-cdn-app"] = app
            cfg["headers"] = hdrs
            worker = self._fetch(self.site_url + "/static/web/js/plugins/crypto-worker.js")
            def _dec_codes(raw):
                if "_" in raw:
                    try:
                        return "".join(chr(int(p)) for p in raw.split("_") if p.strip().isdigit())
                    except Exception:
                        return ""
                return raw
            kraw = _fld(worker, "media_key")
            iraw = _fld(worker, "media_iv")
            k = _dec_codes(kraw)
            v = _dec_codes(iraw)
            if len(k) == 16:
                cfg["key"] = k.encode("utf-8")
            if len(v) == 16:
                cfg["iv"] = v.encode("utf-8")
        except Exception:
            pass
        self._cfg_cache = (now, cfg)
        return cfg

    def _fetch_bytes(self, url, timeout=15, extra_headers=None):
        try:
            ctx = ssl._create_unverified_context()
        except Exception:
            ctx = None
        headers = {"User-Agent": self.headers["User-Agent"],
                   "Referer": self.site_url + "/"}
        if extra_headers:
            headers.update(extra_headers)
        try:
            req = urllib.request.Request(url, headers=headers)
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ctx),
                urllib.request.HTTPCookieProcessor(self._cj))
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                enc = (resp.headers.get("Content-Encoding", "") or "").lower()
                if "gzip" in enc or raw[:2] == b"\x1f\x8b":
                    import gzip
                    raw = gzip.decompress(raw)
                return raw
        except Exception:
            return b""
        return b""

    @staticmethod
    def _pkcs7_unpad(pt):
        if not pt:
            return b""
        pad = pt[-1]
        if 1 <= pad <= 16 and len(pt) >= pad and pt[-pad:] == bytes([pad]) * pad:
            return pt[:-pad]
        return pt

    @staticmethod
    def _aes_cbc_decrypt(key, iv, data):
        # javax.crypto (Jython 真机) -> Crypto -> cryptography -> 纯 Python
        try:
            from javax.crypto import Cipher as _JCipher
            from javax.crypto.spec import SecretKeySpec as _JKey, IvParameterSpec as _JIV
            from java.lang import Byte as _JByte
            c = _JCipher.getInstance("AES/CBC/NoPadding")
            c.init(_JCipher.DECRYPT_MODE, _JKey(key, "AES"), _JIV(iv))
            out = c.doFinal(bytearray(data))
            return bytes(bytearray(out))
        except Exception:
            pass
        try:
            from Crypto.Cipher import AES as _AES
            return _AES.new(key, _AES.MODE_CBC, iv).decrypt(data)
        except Exception:
            pass
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher as _CC, algorithms as _CA, modes as _CM
            dec = _CC(_CA.AES(key), _CM.CBC(iv)).decryptor()
            return dec.update(data) + dec.finalize()
        except Exception:
            pass
        try:
            if len(key) == 16 and len(data) % 16 == 0:
                return _aes_cbc_decrypt_pure(key, iv, data)
        except Exception:
            pass
        return b""

    @staticmethod
    def _img_mime(data):
        if data[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        if data[:3] == b"GIF":
            return "image/gif"
        return ""

    def _decrypt_cover_bytes(self, raw, key, iv):
        if not raw or not key or not iv or len(raw) % 16 != 0:
            return b"", ""
        pt = self._aes_cbc_decrypt(key, iv, raw)
        if not pt:
            return b"", ""
        pt = self._pkcs7_unpad(pt)
        # CryptoJS NoPadding 回落时尾部填充可能残留：JPEG 按 EOI 截断
        if pt[:3] == b"\xff\xd8\xff":
            end = pt.find(b"\xff\xd9")
            if end != -1:
                pt = pt[:end + 2]
        mime = self._img_mime(pt)
        if not mime:
            return b"", ""
        return pt, mime

    def _decrypt_cover_url(self, url):
        for force in (False, True):
            cfg = self._cover_cfg(force=force)
            if not cfg["key"] or not cfg["iv"]:
                continue
            try:
                raw = self._fetch_bytes(url, extra_headers=cfg["headers"])
                if not raw:
                    raw = self._fetch_bytes(url)
            except Exception:
                raw = b""
            if raw:
                body, mime = self._decrypt_cover_bytes(raw, cfg["key"], cfg["iv"])
                if body:
                    return mime, body
        return "", b""

    def _proxy_pic(self, cipher_url):
        # 壳自带代理端口 9978（不是源自己起的 9979+）：壳按 from 找到本源，再调 localProxy
        if not cipher_url:
            return ""
        return ("http://127.0.0.1:9978/proxy?do=py&from=%s&type=pic&url=%s"
                % (urllib.parse.quote(self.getName(), safe=""),
                   urllib.parse.quote(cipher_url, safe="")))

    @staticmethod
    def _enc_pic(tag):
        # data-src / data-fallback-src：密文图地址，不要求图片扩展名
        for attr in ("data-src", "data-fallback-src"):
            mm = re.search(r'%s\s*=\s*["\']([^"\']+)["\']' % attr, tag, re.I)
            if not mm:
                continue
            cand = mm.group(1).strip()
            if cand and not cand.startswith(("blob:", "data:")) and "placeholder" not in cand.lower() and "drama-loading" not in cand:
                return cand
        return ""

    @staticmethod
    def _enc_pic_any(text):
        for attr in ("data-src", "data-fallback-src"):
            for mm in re.finditer(r'%s\s*=\s*["\']([^"\']+)["\']' % attr, text or "", re.I):
                cand = mm.group(1).strip()
                if cand and not cand.startswith(("blob:", "data:")) and "placeholder" not in cand.lower() and "drama-loading" not in cand:
                    return cand
        return ""

    def localProxy(self, params):
        try:
            if isinstance(params, str):
                import json as _json
                try:
                    params = _json.loads(params)
                except Exception:
                    params = {}
            if not isinstance(params, dict):
                params = {}
            url = (params.get("url") or params.get("pic") or "").strip()
            if url.startswith("http://127.0.0.1"):
                return [400, "text/plain", b""]
            if url:
                cache = getattr(self, "_pic_cache", None)
                if cache is None:
                    cache = self._pic_cache = {}
                if url in cache:
                    return cache[url]
                mime, body = self._decrypt_cover_url(url)
                if body:
                    res = [200, mime, body]
                    cache[url] = res
                    return res
            return [404, "text/plain", b""]
        except Exception:
            return [404, "text/plain", b""]


    def action(self, action):
        return None

    def liveContent(self):
        return {}


if __name__ == "__main__":
    sp = Spider()
    html_data = ('<a href="/duanju/123-abc/"><img src="https://img.example.com/1.jpg" alt="测">'
                 '<h3>测</h3></a>'
                 '<a href="/duanju/124-def/"><img src="blob:https://e388.ak29x31k.cc/uuid" alt="测二">'
                 '<h3>测二</h3></a>')
    print(sp._parse_cards(html_data))
    print(sp._list_url("/duanju/", 2))
