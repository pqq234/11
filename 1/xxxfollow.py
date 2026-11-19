# -*- coding: utf-8 -*-
# xxxfollow - https://www.xxxfollow.com/
# 短视频站，沉浸连刷格式
# 卡片: /{username}/{id}-{slug}，封面 ..._small.webp，标题 img alt
# 分类: 50 个 tag（/tag/{name}），全收录
# 播放: 详情页直给 mp4（media/fans/post_public/...mp4），正则首个
# 连刷: feed_stream 分类，点进拼 150 集选集，feed_fetch@@ 懒加载

import re
import ssl
import time
import random
import urllib.parse
import urllib.request

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    from spider import Spider as BaseSpider


class Spider(BaseSpider):
    def getName(self):
        return "xxxfollow"

    def init(self, extend=""):
        self.host = "https://www.xxxfollow.com"
        self.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.headers = {
            "User-Agent": self.ua,
            "Referer": self.host + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def _get(self, url, timeout=12):
        import http.client
        for _ in range(2):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                try:
                    with urllib.request.urlopen(req, timeout=timeout, context=self.ctx) as resp:
                        t = resp.read().decode("utf-8", errors="ignore")
                except http.client.IncompleteRead as e:
                    t = e.partial.decode("utf-8", errors="ignore")
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

    def _abs(self, u):
        if not u:
            return ""
        u = u.replace("&amp;", "&")
        if u.startswith("http"):
            return u
        return self.host.rstrip("/") + "/" + u.lstrip("/")

    def _clean(self, s):
        s = re.sub(r"<[^>]+>", "", s or "")
        s = s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
        return re.sub(r"\s+", " ", s).strip()

    def homeContent(self, filter):
        classes = [{"type_id": "feed_stream", "type_name": "🔥沉浸连刷"}]
        seen = {"feed_stream"}
        html = self._get(self.host + "/")
        # 50 个 tag 全收：/tag/{name}
        for m in re.finditer(r'href="(/tag/([a-zA-Z0-9_-]+))"', html):
            url, name = m.group(1), m.group(2)
            if url in seen:
                continue
            seen.add(url)
            classes.append({"type_id": url, "type_name": "#" + name})
        return {"class": classes, "filters": {}}

    def _cards(self, html):
        cards = []
        seen = set()
        for lm in re.finditer(r'href="((/[^"/\s]+/\d+-[^"\s]*))"', html):
            href = lm.group(1)
            # vid 用 id 部分，保证唯一
            vm = re.search(r'/(\d+)-', href)
            vid = vm.group(1) if vm else href
            if vid in seen:
                continue
            seen.add(vid)
            ctx = html[lm.end():lm.end() + 3000]
            # 标题：img alt 优先
            title = ""
            am = re.search(r'alt="([^"]{3,120})"', ctx)
            if am:
                title = self._clean(am.group(1))
            if not title or len(title) < 3:
                sm = re.search(r'/(\d+)-([^"/\s]+)', href)
                if sm:
                    title = sm.group(2).replace("-", " ").strip()
            # 封面：_small.webp
            pic = ""
            pm = re.search(r'<img[^>]*src="((?:https://www\.xxxfollow\.com)?/media/fans/post_public/[^"]*_small\.webp[^"]*)"', ctx)
            if not pm:
                pm = re.search(r'<img[^>]*src="([^"]+)"', ctx)
            if pm and not pm.group(1).startswith("data:"):
                pic = self._abs(pm.group(1))
            cards.append({
                "vod_id": href,  # 保留完整路径，详情跟 301
                "vod_name": (title[:50] if title else "xxxfollow video"),
                "vod_pic": pic,
                "vod_remarks": "",
            })
            if len(cards) >= 60:
                break
        return cards

    def homeVideoContent(self):
        html = self._get(self.host + "/")
        return {"list": self._cards(html)}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        if tid == "feed_stream":
            tags = ["/tag/nsfw", "/tag/blowjob", "/tag/orgasm", "/tag/petitegonewild",
                    "/tag/doggystyle", "/tag/cute", "/tag/sex", "/tag/asstastic"]
            random.shuffle(tags)
            cards = []
            for t in tags[:3]:
                html = self._get(self.host + t)
                cards = self._cards(html)
                if cards:
                    break
            if not cards:
                cards = self._cards(self._get(self.host + "/"))
            random.shuffle(cards)
            items = [{
                "vod_id": "feed@@%s" % c["vod_id"],
                "vod_name": c["vod_name"],
                "vod_pic": c["vod_pic"],
                "vod_remarks": "连刷起播",
            } for c in cards[:40]]
            return {"list": items, "page": 1, "pagecount": 1, "limit": 40, "total": 40}
        url = self._abs(tid)
        if pg > 1:
            url = url.rstrip("/") + "?page=%d" % pg
        html = self._get(url)
        items = self._cards(html)
        return {"list": items, "page": pg, "pagecount": 99, "limit": len(items), "total": 9999}

    def _stream_of(self, href):
        # href 是卡片路径，详情跟 301 跳转
        html = self._get(self._abs(href))
        if not html:
            return ""
        m = re.search(r'(https://www\.xxxfollow\.com/media/fans/post_public/[^"\s]+\.mp4[^"\s#]*)', html)
        if m:
            return m.group(1).replace("&amp;", "&")
        return ""

    def detailContent(self, ids):
        raw = str(ids[0])
        if raw.startswith("feed@@"):
            start_href = raw.split("@@", 1)[1]
            stream = self._stream_of(start_href)
            pool, seen = [], {start_href}
            tags = ["/tag/nsfw", "/tag/blowjob", "/tag/orgasm", "/tag/petitegonewild",
                    "/tag/doggystyle", "/tag/cute", "/tag/sex", "/tag/asstastic",
                    "/tag/freeuse", "/tag/holdthemoan"]
            random.shuffle(tags)
            for t in tags:
                html = self._get(self.host + t)
                for c in self._cards(html):
                    if c["vod_id"] not in seen:
                        seen.add(c["vod_id"])
                        pool.append(c["vod_id"])
                if len(pool) >= 150:
                    break
            random.shuffle(pool)
            first = stream if stream else "feed_fetch@@%s" % start_href
            episodes = ["$%s" % first]
            for v in pool[:150]:
                episodes.append("$feed_fetch@@%s" % v)
            return {"list": [{
                "vod_id": raw,
                "vod_name": "🔥沉浸连刷",
                "vod_pic": "",
                "vod_play_from": "xxxfollow",
                "vod_play_url": "#".join(episodes),
            }]}
        href = raw
        html = self._get(self._abs(href))
        title = "xxxfollow video"
        tm = re.search(r"<title>([^<]+)</title>", html)
        if tm:
            title = self._clean(tm.group(1)).split("|")[0].strip()[:50] or title
        pm = re.search(r'property="og:image"\s+content="([^"]+)"', html)
        pic = self._abs(pm.group(1)) if pm else ""
        stream = self._stream_of(href)
        target = stream if stream else "rec_fetch@@%s" % href
        return {"list": [{
            "vod_id": href,
            "vod_name": title,
            "vod_pic": pic,
            "vod_play_from": "xxxfollow",
            "vod_play_url": "正片$%s" % target,
        }]}

    def playerContent(self, flag, id, vipFlags):
        raw = str(id).strip()
        url = ""
        if "@@" in raw:
            url = self._stream_of(raw.split("@@", 1)[1])
        elif raw.startswith("http"):
            url = raw
        else:
            url = self._stream_of(raw)
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": {"User-Agent": self.ua, "Referer": self.host + "/"},
        }

    def searchContent(self, key, quick, pg="1"):
        return {"list": []}
