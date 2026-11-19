# -*- coding: utf-8 -*-
# reelsmunkey - https://reelsmunkey.com/
# 短视频站，沉浸连刷格式（Next.js __NEXT_DATA__，无 WAF）
# 列表: 首页 __NEXT_DATA__ → props.pageProps.data[]（20条）
#   每条 _id/title/link(zMZoVA.mp4)/thumbnail(9o4Hf6.webp)/url(slug)/tags[]
# 封面: https://imgs.reelsmunkey.com/{thumbnail}；播放: https://imgs.reelsmunkey.com/{link}（直链无签名）
# 分类: pageProps.tags[]（{tag, url}），分类页 /collections/{url}（同结构，?page=N 翻页）
# 连刷: feed_stream 分类，点进拼 150 集选集，feed_fetch@@ 懒加载

import re
import ssl
import time
import json
import random
import urllib.parse
import urllib.request

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    from spider import Spider as BaseSpider


class Spider(BaseSpider):
    def getName(self):
        return "reelsmunkey"

    def init(self, extend=""):
        self.host = "https://reelsmunkey.com"
        self.img = "https://imgs.reelsmunkey.com"
        self.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.headers = {
            "User-Agent": self.ua,
            "Referer": self.host + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        self._tags = []

    def _get(self, url, timeout=12):
        for _ in range(2):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=timeout, context=self.ctx) as resp:
                    t = resp.read().decode("utf-8", errors="ignore")
                    if len(t) > 1000:
                        return t
            except Exception:
                time.sleep(0.3)
        try:
            r = self.fetch(url, headers=self.headers)
            t = r.text or ""
            if len(t) > 1000:
                return t
        except Exception:
            pass
        return ""

    def _props(self, url):
        html = self._get(url)
        if not html:
            return {}
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
        if not m:
            return {}
        try:
            return json.loads(m.group(1)).get("props", {}).get("pageProps", {})
        except Exception:
            return {}

    def _clean(self, s):
        s = re.sub(r"<[^>]+>", "", s or "")
        s = s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
        return re.sub(r"\s+", " ", s).strip()

    def _cards(self, items):
        cards = []
        seen = set()
        for v in items or []:
            if not isinstance(v, dict):
                continue
            vid = str(v.get("_id", ""))
            link = str(v.get("link", "") or "")
            if not vid or not link or vid in seen:
                continue
            seen.add(vid)
            thumb = str(v.get("thumbnail", "") or "")
            cards.append({
                "vod_id": vid,
                "vod_name": self._clean(str(v.get("title", "")))[:50] or "reelsmunkey video",
                "vod_pic": (self.img + "/" + thumb) if thumb else "",
                "vod_remarks": "",
                "_link": link,
            })
        return cards

    def _tags_list(self):
        if not self._tags:
            pp = self._props(self.host + "/")
            tags = pp.get("tags", []) or []
            for t in tags:
                if isinstance(t, dict) and t.get("tag") and t.get("url"):
                    self._tags.append({"tag": str(t["tag"]), "url": str(t["url"])})
        return self._tags

    def homeContent(self, filter):
        classes = [{"type_id": "feed_stream", "type_name": "🔥沉浸连刷"}]
        seen = {"feed_stream"}
        for t in self._tags_list():
            tid = "col:" + t["url"]
            if tid in seen:
                continue
            seen.add(tid)
            classes.append({"type_id": tid, "type_name": t["tag"]})
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        pp = self._props(self.host + "/")
        cards = self._cards(pp.get("data", []))
        return {"list": [{k: c[k] for k in ("vod_id", "vod_name", "vod_pic", "vod_remarks")} for c in cards]}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        if tid == "feed_stream":
            tags = self._tags_list()
            random.shuffle(tags)
            pool, seen = [], set()
            for t in tags[:5]:
                pp = self._props("%s/collections/%s" % (self.host, t["url"]))
                for c in self._cards(pp.get("data", [])):
                    if c["vod_id"] not in seen:
                        seen.add(c["vod_id"])
                        pool.append(c)
                if len(pool) >= 40:
                    break
            if not pool:
                pp = self._props(self.host + "/")
                pool = self._cards(pp.get("data", []))
            random.shuffle(pool)
            items = [{
                "vod_id": "feed@@%s" % c["vod_id"],
                "vod_name": c["vod_name"],
                "vod_pic": c["vod_pic"],
                "vod_remarks": "连刷起播",
            } for c in pool[:40]]
            return {"list": items, "page": 1, "pagecount": 1, "limit": len(items), "total": len(items)}
        col = tid[4:] if tid.startswith("col:") else ""
        url = "%s/collections/%s" % (self.host, col)
        if pg > 1:
            url += "?page=%d" % pg
        pp = self._props(url)
        cards = self._cards(pp.get("data", []))
        items = [{k: c[k] for k in ("vod_id", "vod_name", "vod_pic", "vod_remarks")} for c in cards]
        try:
            total = int(pp.get("count", 0))
        except Exception:
            total = 0
        return {"list": items, "page": pg, "pagecount": 999 if total == 0 else (total + 19) // 20,
                "limit": len(items), "total": total}

    def _link_of(self, vid):
        # 在首页/分类里找 _id 对应的 link（直链无签名，可缓存于本次调用）
        pp = self._props(self.host + "/")
        for c in self._cards(pp.get("data", [])):
            if c["vod_id"] == str(vid):
                return c["_link"]
        for t in self._tags_list()[:6]:
            pp = self._props("%s/collections/%s" % (self.host, t["url"]))
            for c in self._cards(pp.get("data", [])):
                if c["vod_id"] == str(vid):
                    return c["_link"]
        return ""

    def detailContent(self, ids):
        raw = str(ids[0])
        if raw.startswith("feed@@"):
            start_vid = raw.split("@@", 1)[1]
            pool, seen = [], {start_vid}
            tags = self._tags_list()
            random.shuffle(tags)
            for t in tags:
                pp = self._props("%s/collections/%s" % (self.host, t["url"]))
                for c in self._cards(pp.get("data", [])):
                    if c["vod_id"] not in seen:
                        seen.add(c["vod_id"])
                        pool.append(c["vod_id"])
                if len(pool) >= 150:
                    break
            random.shuffle(pool)
            episodes = ["$feed_fetch@@%s" % start_vid]
            for v in pool[:150]:
                episodes.append("$feed_fetch@@%s" % v)
            return {"list": [{
                "vod_id": raw,
                "vod_name": "🔥沉浸连刷",
                "vod_pic": "",
                "vod_play_from": "reelsmunkey",
                "vod_play_url": "#".join(episodes),
            }]}
        vid = raw
        link = self._link_of(vid)
        target = (self.img + "/" + link) if link else "fetch@@%s" % vid
        return {"list": [{
            "vod_id": vid,
            "vod_name": "reelsmunkey video",
            "vod_pic": "",
            "vod_play_from": "reelsmunkey",
            "vod_play_url": "正片$%s" % target,
        }]}

    def playerContent(self, flag, id, vipFlags):
        raw = str(id).strip()
        url = ""
        if "@@" in raw:
            link = self._link_of(raw.split("@@", 1)[1])
            url = (self.img + "/" + link) if link else ""
        elif raw.startswith("http"):
            url = raw
        else:
            link = self._link_of(raw)
            url = (self.img + "/" + link) if link else ""
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": {"User-Agent": self.ua, "Referer": self.host + "/"},
        }

    def searchContent(self, key, quick, pg="1"):
        return {"list": []}
