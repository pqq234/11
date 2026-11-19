# -*- coding: utf-8 -*-
# PandaLive (팬더티비) — TVBox py 直播源
# 站点结构(实测 2026-10-24):
#   列表: GET https://cache-api.pandalive.co.kr/v1/live/index
#         ?offset&limit(<=100)&viewerType=0&deviceType=webMobile&lang=ko
#         [&orderBy=hot|new|user][&onlyNewBj=Y][&onlyRealTimeYN=Y]
#         -> {"list":[...], "page":{"total":N, "lastPage":M}} 真分页
#   分类: 站方无服务端分类过滤(客户端实测 category 参数被忽略)：
#         分类为 2026-10-24 实测内置表，题材分类为全量本地过滤，
#         复测时确认在线规模与分类是否为最新全集；
#         排序预设走接口参数；题材分类(ind/music/game/talk/adt/etc)
#         拉全量在线列表后本地过滤(总数约 220，3 次请求内)。
#   房间: vod_id = userIdx；房间页 https://m.pandalive.co.kr/play/{userIdx}
#   播放: POST https://api.pandalive.co.kr/v1/live/play
#         form: userId={userIdx}&action=watch -> PlayList.hls/hls2/hls3
#         为 AWS IVS 的 m3u8(带 token)。两个实测结论决定播放走 localProxy:
#         (1) 拉清单必须带 Referer+Origin，不带返回 403(同 URL 对照验过)；
#         (2) 主清单 URL 是「一次性」的: 第 1 次 GET 200 #EXTM3U，
#             第 2 次起 403(响应体为 JSON)。子清单/分片可重复拉。
#         故 player 下发 localProxy 地址，代理内现调 play 拿新 token、
#         只拉一次主清单原样下发，子清单由播放器直连。player 内严禁
#         对主清单探活——探活会把唯一一次取流机会消耗掉。
#   限制(站方规则，游客态如实返回):
#         isAdult 房间 play 回 본인인증 필요(韩国实名认证)，游客不可播；
#         type=fan 房间回 로그인 필요(需登录)；isPw 房间需密码。
#         这三类 player 退回房间页 parse=1，不伪造可播。
#   搜索: POST /v1/live/bj_list (searchVal/limit/offset) 搜 BJ，
#         结果带 media 的是正在播的房间，只收这类(下播的搜到也不能播)。
#   封面: list.thumbUrl 为 CDN 直链 JPEG(实测 ffd8ff 魔数)，无需代理。
import re
import ssl
import time
import json
import gzip
import urllib.request
import urllib.parse
from http.cookiejar import CookieJar

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass


class Spider(BaseSpider):

    API = "https://api.pandalive.co.kr"
    CACHE_API = "https://cache-api.pandalive.co.kr"
    SITE = "https://m.pandalive.co.kr"

    # (type_id, 名称) —— type_id: all / 排序预设 / cat:<题材代码>
    CATS = [
        ("all", "전체 라이브"),
        ("rt", "실시간"),
        ("hot", "인기"),
        ("new", "최신"),
        ("user", "시청자순"),
        ("newbj", "신규 BJ"),
        ("cat:ind", "개인방송"),
        ("cat:music", "음악"),
        ("cat:game", "게임"),
        ("cat:talk", "토크"),
        ("cat:adt", "성인"),
        ("cat:etc", "기타"),
    ]
    CAT_NAMES = {"ind": "개인방송", "music": "음악", "game": "게임",
                 "talk": "토크", "adt": "성인", "etc": "기타", "all": "전체"}
    PAGE_SIZE = 40

    def __init__(self):
        self.site_url = self.SITE
        self.ua = ("Mozilla/5.0 (Linux; Android 13; SM-G991B) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/131.0.0.0 Mobile Safari/537.36")
        self.headers = {
            "User-Agent": self.ua,
            "Accept": "*/*",
            "Accept-Language": "ko",
            "X-Device-Info": '{"t":"webMobile","v":"1.0","ui":0}',
            "Origin": self.SITE,
            "Referer": self.SITE + "/",
            "Connection": "keep-alive",
        }
        self.cookie_jar = CookieJar()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx),
            urllib.request.HTTPCookieProcessor(self.cookie_jar))
        # 节流：接口限流保护，非全局无意义延时；命中限流时另走递增重试。
        self._throttle = 0.5
        self._last_req = 0.0
        self._all_cache = None       # 题材分类用的全量列表缓存
        self._all_cache_at = 0.0

    # ---------- 基础抓取 ----------
    def _request(self, url, data=None, retry=2, timeout=15):
        gap = time.time() - self._last_req
        if gap < self._throttle:
            time.sleep(self._throttle - gap)
        self._last_req = time.time()
        body = None
        headers = dict(self.headers)
        if data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        for i in range(retry + 1):
            try:
                req = urllib.request.Request(url, data=body, headers=headers)
                with self.opener.open(req, timeout=timeout) as resp:
                    raw = resp.read()
                    if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                        raw = gzip.decompress(raw)
                    if not raw:
                        raise IOError("empty response")
                    return raw.decode("utf-8", "ignore")
            except Exception:
                if i < retry:
                    time.sleep(0.5 * (i + 1))
        return ""

    def _api_list(self, params):
        q = {"viewerType": "0", "deviceType": "webMobile", "lang": "ko"}
        q.update(params)
        url = self.CACHE_API + "/v1/live/index?" + urllib.parse.urlencode(q)
        text = self._request(url)
        if not text:
            return {}, {}
        try:
            d = json.loads(text)
            return d.get("list") or [], d.get("page") or {}
        except Exception:
            return [], {}

    def _api_play(self, user_idx, password=None):
        data = {"userId": str(user_idx), "action": "watch"}
        if password:
            data["password"] = password
        text = self._request(self.API + "/v1/live/play", data=data)
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            return {}

    def _api_bj_search(self, key, offset, limit):
        text = self._request(self.API + "/v1/live/bj_list", data={
            "searchVal": key, "limit": str(limit), "offset": str(offset)})
        if not text:
            return [], {}
        try:
            d = json.loads(text)
            return d.get("list") or [], d.get("page") or {}
        except Exception:
            return [], {}

    # ---------- 数据整形 ----------
    @staticmethod
    def _clean(s):
        if not s:
            return ""
        s = re.sub(r"<[^>]+>", "", str(s))
        for k, v in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                     ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
            s = s.replace(k, v)
        return s.strip()

    def _card(self, it):
        if not it:
            return None
        idx = it.get("userIdx")
        if not idx:
            return None
        name = self._clean(it.get("title") or "") or self._clean(it.get("userNick") or "")
        if not name:
            return None
        remarks = []
        if it.get("isAdult"):
            remarks.append("🔞")
        if it.get("isPw"):
            remarks.append("🔒")
        if it.get("type") == "fan":
            remarks.append("팬전용")
        try:
            remarks.append("%d명" % int(it.get("user") or 0))
        except Exception:
            pass
        return {
            "vod_id": str(idx),
            "vod_name": name,
            "vod_pic": it.get("thumbUrl") or "",
            "vod_remarks": " ".join(remarks),
            "style": {"type": "rect", "ratio": 1.78},
        }

    def _sort_params(self, tid):
        if tid == "rt":
            return {"orderBy": "hot", "onlyRealTimeYN": "Y"}
        if tid == "hot":
            return {"orderBy": "hot"}
        if tid == "new":
            return {"orderBy": "new"}
        if tid == "user":
            return {"orderBy": "user"}
        if tid == "newbj":
            return {"orderBy": "user", "onlyNewBj": "Y"}
        return {}

    def _all_rooms(self):
        """题材分类用: 拉全量在线列表(接口上限 100/次)。60 秒内复用缓存。"""
        now = time.time()
        if self._all_cache is not None and now - self._all_cache_at < 60:
            return self._all_cache
        rooms, seen = [], set()
        offset = 0
        while offset < 1000:
            lst, page = self._api_list({"offset": offset, "limit": 100})
            if not lst:
                break
            for it in lst:
                code = it.get("code")
                if code and code not in seen:
                    seen.add(code)
                    rooms.append(it)
            offset += len(lst)
            total = page.get("total") or 0
            if not total or offset >= total:
                break
        self._all_cache = rooms
        self._all_cache_at = now
        return rooms

    # ---------- TVBox 接口 ----------
    def getName(self):
        return "PandaLive"

    def init(self, extend=""):
        cfg = {}
        if extend:
            try:
                cfg = json.loads(extend) if isinstance(extend, str) else dict(extend)
            except Exception:
                cfg = {}
        if isinstance(cfg, dict):
            if cfg.get("cookie"):
                self.headers["Cookie"] = str(cfg["cookie"])
            if cfg.get("token"):
                self.headers["Authorization"] = "Bearer " + str(cfg["token"])
        return True

    def homeContent(self, filter):
        return {"class": [{"type_id": t, "type_name": n} for t, n in self.CATS],
                "filters": {}}

    def homeVideoContent(self):
        lst, _ = self._api_list({"offset": 0, "limit": self.PAGE_SIZE})
        return {"list": [c for c in (self._card(x) for x in lst) if c]}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        tid = str(tid or "all")
        if tid.startswith("cat:"):
            code = tid[4:]
            rooms = [x for x in self._all_rooms() if x.get("category") == code]
            total = len(rooms)
            pagecount = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
            part = rooms[(pg - 1) * self.PAGE_SIZE: pg * self.PAGE_SIZE]
            cards = [c for c in (self._card(x) for x in part) if c]
            return {"list": cards, "page": pg, "pagecount": pagecount,
                    "limit": len(cards), "total": total}
        params = {"offset": (pg - 1) * self.PAGE_SIZE, "limit": self.PAGE_SIZE}
        params.update(self._sort_params(tid))
        lst, page = self._api_list(params)
        cards = [c for c in (self._card(x) for x in lst) if c]
        pagecount = page.get("lastPage") or (pg + 1 if cards else pg)
        return {"list": cards, "page": pg, "pagecount": int(pagecount),
                "limit": len(cards), "total": int(page.get("total") or 0)}

    def _play_groups(self, data):
        """PlayList -> [(group_key, label, url)] 按 hls3(RT) > hls > hls2，同 URL 去重。"""
        out, seen_url = [], set()
        pl = (data or {}).get("PlayList") or {}
        for key in ("hls3", "hls", "hls2"):
            for ent in pl.get(key) or []:
                u = (ent.get("url") or "").strip()
                if not u or u in seen_url:
                    continue
                seen_url.add(u)
                label = self._clean(ent.get("name") or "") or "자동"
                out.append((key, "%s(%s)" % (label, key.upper()), u))
        return out

    def detailContent(self, ids):
        vid = str(ids[0]).strip() if ids else ""
        if not vid:
            return {"list": []}
        data = self._api_play(vid)
        media = data.get("media") or {}
        groups = self._play_groups(data)
        if not media:
            # 成年/粉丝房 play 被拒时没有 media 字段:
            # 从全量在线列表里找同一房间回填名称/封面
            for it in self._all_rooms():
                if str(it.get("userIdx")) == vid:
                    media = it
                    break
        name = self._clean(media.get("title") or "") or vid
        content = []
        if media.get("userNick"):
            content.append("BJ: %s (%s)" % (self._clean(media["userNick"]),
                                           media.get("userId", "")))
        if media.get("category"):
            content.append("분류: %s" % self.CAT_NAMES.get(media["category"],
                                                         media["category"]))
        if media.get("user") is not None:
            content.append("시청자: %s명" % media.get("user"))
        if media.get("startTime"):
            content.append("시작: %s" % media["startTime"])
        if media.get("isAdult"):
            content.append("성인 방송: 본인인증 필요(游客不可播)")
        if media.get("type") == "fan":
            content.append("팬 전용 방송: 로그인 필요")
        if media.get("isPw"):
            content.append("비밀번호 방송")
        if groups:
            eps = ["%s$%s|%s" % (label, vid, key) for key, label, _u in groups]
        else:
            eps = ["재생$%s|auto" % vid]
        remarks = []
        if media.get("isAdult"):
            remarks.append("🔞")
        if media.get("isPw"):
            remarks.append("🔒")
        vod = {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": media.get("thumbUrl") or "",
            "vod_remarks": " ".join(remarks),
            "vod_actor": self._clean(media.get("userNick") or ""),
            "vod_content": " · ".join(content),
            "vod_play_from": "PandaLive",
            "vod_play_url": "#".join(eps),
        }
        return {"list": [vod]}

    def _play_header(self):
        return {"User-Agent": self.ua,
                "Referer": self.SITE + "/",
                "Origin": self.SITE}

    def _proxy_url(self, idx, group):
        q = "type=m3u8&idx=%s&group=%s" % (urllib.parse.quote(str(idx)),
                                          urllib.parse.quote(str(group)))
        base = None
        try:
            base = self.getProxyUrl()
        except Exception:
            base = None
        if base:
            sep = "&" if "?" in base else "?"
            return base + sep + q
        # 2026-10-27 更新：不再写死本地代理基址；壳不提供代理地址时
        # 返回空，playerContent 据此退回房间页，不伪造可播地址。
        return ""

    def _fetch_master_once(self, url):
        """主清单只许拉一次(一次性 token)，单次尝试、不重试。"""
        try:
            req = urllib.request.Request(url, headers=self._play_header())
            with self.opener.open(req, timeout=15) as resp:
                raw = resp.read()
                if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8", "ignore")
                return text if "#EXTM3U" in text else ""
        except Exception:
            return ""

    def playerContent(self, flag, id, vipFlags):
        raw = str(id or "")
        if "|" in raw:
            vid, group = raw.split("|", 1)
        else:
            vid, group = raw, "auto"
        room_url = "%s/play/%s" % (self.SITE, vid)
        try:
            # 只调 play 接口确认房间此刻可播；不碰主清单(一次性)
            data = self._api_play(vid)
            if self._play_groups(data):
                proxy_url = self._proxy_url(vid, group)
                if proxy_url:
                    return {"parse": 0, "url": proxy_url,
                            "header": self._play_header()}
                # 无代理地址时不下发写死地址，退回房间页。
        except Exception:
            pass
        # 站方拒绝(성인 인증/팬 전용/비밀번호/已下播): 退回房间页
        return {"parse": 1, "url": room_url, "header": self._play_header()}

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        key = str(key or "").strip()
        if not key:
            return {"list": [], "page": pg, "pagecount": pg, "limit": 0, "total": 0}
        lst, page = self._api_bj_search(key, (pg - 1) * self.PAGE_SIZE, self.PAGE_SIZE)
        cards = []
        for bj in lst:
            media = bj.get("media")
            if not media:
                continue  # 未在播的 BJ 搜到也不能播，只收直播中的
            card = self._card(media)
            if card:
                cards.append(card)
        pagecount = page.get("lastPage") or pg
        return {"list": cards, "page": pg, "pagecount": int(pagecount),
                "limit": len(cards), "total": int(page.get("total") or 0)}

    def localProxy(self, params):
        # type=m3u8: 播放主清单中转(一次性 token，现调 play 现拉一次)
        # type=pic: 封面代理(一般用不上，封面 CDN 直链可直接加载)
        try:
            if isinstance(params, dict) and params.get("type") == "m3u8":
                idx = params.get("idx", "")
                group = params.get("group", "auto")
                data = self._api_play(idx)
                groups = self._play_groups(data)
                pick = None
                for key, _label, u in groups:
                    if key == group:
                        pick = u
                        break
                if not pick and groups:
                    pick = groups[0][2]
                if pick:
                    body = self._fetch_master_once(pick)
                    if body:
                        return [200, "application/vnd.apple.mpegurl",
                                body.encode("utf-8")]
                return [404, "text/plain", b""]
            if isinstance(params, dict) and params.get("type") == "pic":
                url = params.get("url", "")
                if url:
                    req = urllib.request.Request(url, headers={"User-Agent": self.ua})
                    with self.opener.open(req, timeout=15) as resp:
                        raw = resp.read()
                    mime = self._img_mime(raw)
                    if mime:
                        return [200, mime, raw]
        except Exception:
            pass
        return [404, "text/plain", b""]

    @staticmethod
    def _img_mime(raw):
        if not raw or len(raw) < 4:
            return ""
        if raw[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if raw[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            return "image/webp"
        return ""

    def isVideoFormat(self, url):
        u = (url or "").lower()
        return ".m3u8" in u or ".mp4" in u

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass
