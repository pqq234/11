# -*- coding: utf-8 -*-
import json
import re
import sys
import uuid
from urllib.parse import quote

import requests

sys.path.append('..')
from base.spider import Spider as BaseSpider

BRAND_NAME = "蝴蝶影视"
BRAND_ACTOR = "🦋 TG群: @tvshare23"
BRAND_DIRECTOR = "🦋 蝴蝶影视"
TG_GROUP = "https://t.me/tvshare23"
SYNOPSIS_GROUP = "🦋 蝴蝶影视官方交流群：@tvshare23"
DIVIDER_THIN = "────────────────────"
DIVIDER_THICK = "━━━━━━━━━━━━━━"
MARKER = "〔影片简介〕"
LINE_NAME = "🦋 蝴蝶专线"
NODE_LINE = "当前节点：https://chengguodj.com"
HOST = "https://chengguodj.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MEDIA_KEY = b"f5d965df75336270"
MEDIA_IV = b"97b60394abc2fbe1"
_SBOX = bytes.fromhex("637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b27509832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cfd0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdbe0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9ee1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
_INV_SBOX = bytearray(256)
for _i in range(256):
    _INV_SBOX[_SBOX[_i]] = _i


def _gf_mul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def _expand_key(key):
    w = list(key)
    rcon = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]
    for i in range(4, 44):
        temp = w[4 * (i - 1):4 * i]
        if i % 4 == 0:
            temp = [_SBOX[temp[1]] ^ rcon[i // 4 - 1], _SBOX[temp[2]], _SBOX[temp[3]], _SBOX[temp[0]]]
        for j in range(4):
            w.append(w[4 * (i - 4) + j] ^ temp[j])
    return w


def _decrypt_block(block, w):
    s = list(block)

    def add_round_key(rnd):
        for i in range(16):
            s[i] ^= w[16 * rnd + i]

    def inv_shift_rows():
        old = s[:]
        for r in range(4):
            for c in range(4):
                s[4 * c + r] = old[4 * ((c - r) % 4) + r]

    def inv_sub_bytes():
        for i in range(16):
            s[i] = _INV_SBOX[s[i]]

    def inv_mix_columns():
        for c in range(4):
            i = 4 * c
            a0, a1, a2, a3 = s[i], s[i + 1], s[i + 2], s[i + 3]
            s[i] = _gf_mul(a0, 14) ^ _gf_mul(a1, 11) ^ _gf_mul(a2, 13) ^ _gf_mul(a3, 9)
            s[i + 1] = _gf_mul(a0, 9) ^ _gf_mul(a1, 14) ^ _gf_mul(a2, 11) ^ _gf_mul(a3, 13)
            s[i + 2] = _gf_mul(a0, 13) ^ _gf_mul(a1, 9) ^ _gf_mul(a2, 14) ^ _gf_mul(a3, 11)
            s[i + 3] = _gf_mul(a0, 11) ^ _gf_mul(a1, 13) ^ _gf_mul(a2, 9) ^ _gf_mul(a3, 14)

    add_round_key(10)
    for rnd in range(9, 0, -1):
        inv_shift_rows()
        inv_sub_bytes()
        add_round_key(rnd)
        inv_mix_columns()
    inv_shift_rows()
    inv_sub_bytes()
    add_round_key(0)
    return bytes(s)


def _aes_cbc_decrypt_pure(data, key, iv):
    w = _expand_key(key)
    out = bytearray()
    prev = iv
    for off in range(0, len(data) - 15, 16):
        block = data[off:off + 16]
        dec = _decrypt_block(block, w)
        out.extend(dec[i] ^ prev[i] for i in range(16))
        prev = block
    if out:
        pad = out[-1]
        if 1 <= pad <= 16:
            out = out[:-pad]
    return bytes(out)


def _aes_cbc_decrypt(data, key, iv):
    try:
        from Crypto.Cipher import AES
        return AES.new(key, AES.MODE_CBC, iv).decrypt(data)
    except Exception:
        pass
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        raw = dec.update(data) + dec.finalize()
        if raw:
            pad = raw[-1]
            if 1 <= pad <= 16:
                raw = raw[:-pad]
        return raw
    except Exception:
        pass
    return _aes_cbc_decrypt_pure(data, key, iv)


class Spider(BaseSpider):
    def getName(self):
        return "橙果短剧"

    def init(self, extend=""):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Referer": HOST + "/"})
        self.classes = [
            {"type_id": "browse", "type_name": "全部"},
            {"type_id": "zhenren", "type_name": "真人短剧"},
            {"type_id": "yuanchuang", "type_name": "原创"},
            {"type_id": "mogai", "type_name": "魔改"},
            {"type_id": "manju", "type_name": "漫剧"},
            {"type_id": "aiduanju", "type_name": "AI短剧"},
        ]

    def getDependence(self):
        return []

    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url

    def destroy(self):
        pass

    def _fetch(self, url):
        last = None
        for _ in range(3):
            try:
                r = self.session.get(url, timeout=30)
                if r.status_code == 200 and r.text:
                    return r.text
                last = r.status_code
            except Exception as e:
                last = e
        raise RuntimeError(str(last))

    def _payload(self, url):
        text = self._fetch(url)
        m = re.search(r'id="__NUXT_DATA__"[^>]*>(.*?)</script>', text, re.S)
        if not m:
            return []
        arr = json.loads(m.group(1))
        memo = {}

        def res(i, depth=0):
            if isinstance(i, bool) or not isinstance(i, int):
                return i
            if i < 0 or i >= len(arr):
                return i
            if i in memo:
                return memo[i]
            if depth > 80:
                return None
            v = arr[i]
            if isinstance(v, list):
                if v and isinstance(v[0], str) and v[0] in ("ShallowReactive", "Reactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef"):
                    out = res(v[1], depth + 1) if len(v) > 1 else None
                    memo[i] = out
                    return out
                out = []
                memo[i] = out
                for x in v:
                    out.append(res(x, depth + 1))
                return out
            if isinstance(v, dict):
                out = {}
                memo[i] = out
                for k, x in v.items():
                    out[k] = res(x, depth + 1)
                return out
            memo[i] = v
            return v

        root = res(1)
        sections = []
        data = root.get("data") if isinstance(root, dict) else None
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, dict) and isinstance(v.get("data"), (dict, list)):
                    sections.append(v["data"])
        return sections

    def _section(self, sections, key):
        for s in sections:
            if isinstance(s, dict) and key in s:
                return s
        return {}

    _proxy_base_cache = None

    @classmethod
    def _proxy_base(cls):
        if cls._proxy_base_cache is not None:
            return cls._proxy_base_cache
        base = ""
        try:
            fn = getattr(cls(), "getProxyUrl", None)
            if callable(fn):
                try:
                    base = fn(local=False) or fn() or ""
                except TypeError:
                    base = fn() or ""
        except Exception:
            base = ""
        cls._proxy_base_cache = str(base or "")
        return cls._proxy_base_cache

    def _proxied(self, url):
        base = Spider._proxy_base()
        if not base:
            return url
        sep = "&" if "?" in base else "?"
        return base + sep + "cg_img=1&u=" + quote(url, safe="")

    def _pic(self, cover, encrypted=None):
        if isinstance(cover, dict):
            url = cover.get("url") or ""
            enc = cover.get("encrypted") if encrypted is None else encrypted
            if url:
                return self._proxied(url) if enc else url
            return ""
        if isinstance(cover, str) and cover:
            return self._proxied(cover) if encrypted else cover
        return ""

    def _remarks(self, d):
        total = d.get("total_episode_count") or d.get("total_episodes") or 0
        pub = d.get("published_episode_count") or d.get("latest_episode_number") or total
        try:
            total = int(total)
            pub = int(pub)
        except Exception:
            return ""
        if total and pub < total:
            return f"更新至{pub}集"
        if total:
            return f"全{total}集"
        if pub:
            return f"更新至{pub}集"
        return ""

    def _vod(self, d):
        cover = d.get("cover")
        if isinstance(cover, dict):
            pic = self._pic(cover)
        elif isinstance(cover, str) and cover:
            pic = self._pic(cover, bool(d.get("cover_encrypted")))
        else:
            pic = ""
        return {
            "vod_id": d.get("slug") or "",
            "vod_name": d.get("title") or "",
            "vod_pic": pic,
            "vod_remarks": self._remarks(d),
        }

    def homeContent(self, filter):
        return {"class": self.classes, "filters": {}}

    def homeVideoContent(self):
        sections = self._payload(HOST + "/")
        sec = self._section(sections, "hot")
        seen = set()
        videos = []
        for key in ("hot", "featured", "freshest"):
            block = sec.get(key) or {}
            items = block.get("items") if isinstance(block, dict) else None
            for d in items or []:
                slug = d.get("slug")
                if slug and slug not in seen:
                    seen.add(slug)
                    videos.append(self._vod(d))
        return {"list": videos}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg)
        url = HOST + "/" + tid if pg <= 1 else HOST + f"/{tid}/page-{pg}"
        sections = self._payload(url)
        sec = self._section(sections, "items")
        items = sec.get("items") or []
        pag = sec.get("pagination") or {}
        total = int(pag.get("total") or len(items))
        pagecount = int(pag.get("total_pages") or 1)
        videos = [self._vod(d) for d in items]
        return {"list": videos, "page": pg, "pagecount": pagecount, "limit": 30, "total": total}

    def detailContent(self, ids):
        did = ids[0]
        sections = self._payload(HOST + "/drama/" + did)
        sec = {}
        for s in sections:
            if isinstance(s, dict) and "episodes" in s and "title" in s:
                sec = s
                break
        title = sec.get("title") or ""
        intro = sec.get("intro") or ""
        channel = sec.get("channel") or {}
        ch_name = channel.get("name") if isinstance(channel, dict) else str(channel or "")
        tags = []
        for t in sec.get("tags") or []:
            if isinstance(t, dict) and t.get("name"):
                tags.append(t["name"])
            elif isinstance(t, str):
                tags.append(t)
        episodes = sec.get("episodes") or []
        parts = []
        for ep in episodes:
            num = ep.get("number")
            if num is None:
                continue
            name = ep.get("title") or ""
            if not name or str(name).strip() in (str(num), f"第{num}集"):
                name = f"第{num}集"
            parts.append(f"{name}${did}/{num}")
        if not parts:
            total = int(sec.get("published_episode_count") or sec.get("total_episode_count") or 0)
            for n in range(1, total + 1):
                parts.append(f"第{n}集${did}/{n}")
        year = ""
        pub_at = sec.get("published_at") or ""
        if isinstance(pub_at, str) and len(pub_at) >= 4:
            year = pub_at[:4]
        content = "\n".join([
            DIVIDER_THICK,
            f"🦋 品牌：{BRAND_NAME}",
            NODE_LINE,
            f"📡 线路：{LINE_NAME}",
            f"👥 交流群：{SYNOPSIS_GROUP}",
            DIVIDER_THIN,
            MARKER,
            intro,
        ])
        vod = {
            "vod_id": did,
            "vod_name": title,
            "vod_pic": self._pic(sec.get("cover")),
            "vod_year": year,
            "vod_area": "",
            "vod_remarks": self._remarks(sec),
            "vod_actor": BRAND_ACTOR,
            "vod_director": BRAND_DIRECTOR,
            "vod_content": content,
            "type_name": " / ".join([x for x in [ch_name] + tags if x]),
            "vod_play_from": LINE_NAME,
            "vod_play_url": "#".join(parts),
        }
        return {"list": [vod]}

    def searchContent(self, key, quick, pg="1"):
        sections = self._payload(HOST + "/search/" + quote(key, safe=""))
        sec = self._section(sections, "dramas")
        dramas = sec.get("dramas") or []
        videos = [self._vod(d) for d in dramas if isinstance(d, dict)]
        return {"list": videos, "page": int(pg), "pagecount": 1, "limit": len(videos), "total": len(videos)}

    def playerContent(self, flag, id, vipFlags):
        sections = self._payload(HOST + "/play/" + id)
        sec = self._section(sections, "media")
        media = sec.get("media") or {}
        url = media.get("source_url") or media.get("h265_url") or ""
        header = {"User-Agent": UA, "Referer": HOST + "/"}
        if url:
            return {"parse": 0, "playUrl": "", "url": url, "header": header}
        return {"parse": 1, "playUrl": "", "url": HOST + "/play/" + id, "header": header}

    def _proxy_image(self, param):
        from urllib.parse import parse_qs, unquote
        if isinstance(param, dict):
            u = param.get("u") or ""
        else:
            q = parse_qs(str(param or ""))
            u = (q.get("u") or [""])[0]
        u = unquote(u)
        if not u.startswith("http"):
            return [400, "text/plain; charset=utf-8", b"bad img url"]
        r = self.session.get(u, timeout=30)
        body = r.content
        if body[:3] == b"\xff\xd8\xff" or body[:4] == b"\x89PNG" or body[:4] == b"RIFF":
            dec = body
        else:
            dec = _aes_cbc_decrypt(body, MEDIA_KEY, MEDIA_IV)
        ctype = "image/jpeg"
        if dec[:4] == b"\x89PNG":
            ctype = "image/png"
        elif dec[:4] == b"RIFF":
            ctype = "image/webp"
        return [200, ctype, dec]

    def localProxy(self, param):
        try:
            return self._proxy_image(param)
        except Exception as e:
            return [400, "text/plain; charset=utf-8", str(e)[:100].encode("utf-8")]

    def proxy(self, param):
        try:
            result = self._proxy_image(param)
            return [result[0], result[1], result[2], {}]
        except Exception as e:
            return [400, "text/plain; charset=utf-8", str(e)[:100].encode("utf-8"), {}]

    def liveContent(self, url):
        return {"list": []}

    def manualVideoCheck(self):
        return False
