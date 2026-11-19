# -*- coding: utf-8 -*-
# TVBox Python Spider: 黄果短剧 (huangdou.me)
# 修复（2026-11-17，实测）：
#  1. 分类补全：新增 最新上架/高分佳作；热门推荐改走 /api/series/popular（原 /popular 页是 JS 空壳，0 内容）；
#     最新上架走 /api/series/ranking?type=latest，高分佳作走 /api/series/ranking?type=score；homeContent 动态发现只探首页
#     （原 /tags、/categories 均 404，/popular 无链接）；12 个标签与首页实测一致。
#  2. 搜索改走真实接口 /api/search（原 3 个 HTML 猜测地址均 0 结果，/search/<kw> 直接 404），按 has_more 真分页。
#  3. 详情选集改走页面内嵌 episodes 数据（number/title/playUrl 直给 m3u8）：修 ser_ 形式 vod_id 取不到选集的问题
#     （原按输入 slug 拼正则，ser_ 链接的剧集 0 选集）；去掉编造的 /play/1 回落；play 链接回落不再限制 slug。
#  4. 播放：按集数取对应 m3u8（原取首个 m3u8，播第 5 集放的还是第 1 集）；m3u8 URL 清洗（去尾部反斜杠、中文路径百分号编码，
#     原 URL 带反斜杠+中文裸字符，urllib 直接报 UnicodeEncodeError）；补 _probe_media 门禁（m3u8 验 #EXTM3U，验不过回落 parse=1）。
#  5. 封面：_format_pic 的 data: 判断移到 _abs 之前（原 _abs 先把 data: 拼成站内地址，判断永不命中）；封面实测为真 JPEG/WEBP，
#     无需解密，维持直出 + @Referer（无 UA 会 403）。
#  6. Session 请求补 proxies=self.session.proxies or None（壳注入代理不带上则被墙站直连失败）；isVideoFormat 改正则判扩展名；
#     localProxy 未知类型默认改 404；destroy 关闭 session。
# ============================================================

import re
import json
import time
import urllib.parse
import urllib.request

try:
    import requests
    _HAS_REQUESTS = True
except Exception:
    _HAS_REQUESTS = False
    requests = None

try:
    from base.spider import Spider as BaseSpider
except Exception:
    try:
        from spider import Spider as BaseSpider
    except Exception:
        class BaseSpider(object):
            pass


class Spider(BaseSpider):
    # 三个榜单走站内 API（实测 2026-11-17）：/popular、/latest、/top-rated 页面本身是 JS 空壳，
    # 前端就是调这些接口取数；接口不认 page/offset，只回固定榜单，categoryContent 里 pg>1 直接返回空页。
    _API_LISTS = {
        "api:popular": "/api/series/popular?limit=50",
        "api:latest": "/api/series/ranking?type=latest&limit=50",
        "api:top-rated": "/api/series/ranking?type=score&limit=50",
    }

    # 详情/播放页内嵌的 episodes 数据（flight 字段，实测结构）：
    # {"id":"ep_...","seriesId":"ser_...","number":1,"title":"第1集","durationSec":0,
    #  "playUrl":"https://...r2.dev/<剧名>/episode_001/playlist.m3u8",...}
    _EP_RE = re.compile(
        r'\\?"number\\?":(\d+),\\?"title\\?":\\"([^"\\]*)\\"[^}]*?\\?"playUrl\\?":\\"([^"\\]+)',
        re.S)

    def init(self, extend=""):
        pass

    def __init__(self):
        super(Spider, self).__init__()
        self.site_name = "黄果短剧"
        self.site_url = "https://huangdou.me"
        self.entry_path = "/"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.site_url + "/",
        }
        self.session = requests.Session() if _HAS_REQUESTS else None
        if self.session:
            self.session.headers.update(self.headers)

    def _fetch(self, url, timeout=15):
        for _ in range(3):
            try:
                if self.session:
                    r = self.session.get(url, headers=self.headers, timeout=timeout,
                                         proxies=self.session.proxies or None)
                    if r.status_code == 200:
                        return r.text
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                    for cs in ("utf-8", "gbk", "gb2312"):
                        try:
                            return raw.decode(cs)
                        except Exception:
                            continue
                    return raw.decode("utf-8", errors="ignore")
            except Exception:
                time.sleep(0.5)
        return ""

    def _fetch_json(self, url, timeout=15):
        try:
            txt = self._fetch(url, timeout=timeout)
            if not txt:
                return {}
            data = json.loads(txt)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _abs(self, path):
        if not path:
            return ""
        path = str(path).strip()
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if path.startswith("//"):
            return "https:" + path
        return urllib.parse.urljoin(self.site_url + "/", path)

    @staticmethod
    def _clean(s):
        if not s:
            return ""
        s = re.sub(r"<[^>]+>", "", s)
        for k, v in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " "), ("&quot;", "\""), ("&#039;", "'")):
            s = s.replace(k, v)
        return re.sub(r"\s+", " ", s).strip()

    def _clean_media_url(self, u):
        """播放地址清洗：去转义反斜杠、去尾部反斜杠、非 ASCII 路径百分号编码。
        站内 m3u8 地址含中文裸字符且嵌在 flight 数据里时尾部会多出反斜杠，
        不处理 urllib 直接报 UnicodeEncodeError、播放器也播不了。"""
        if not u:
            return ""
        u = str(u).replace("\\/", "/").strip().rstrip("\\").strip()
        if not u:
            return ""
        try:
            parts = urllib.parse.urlsplit(u)
            path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/@:+&=%~,;")
            query = urllib.parse.quote(urllib.parse.unquote(parts.query), safe="=&%+@:/?~") if parts.query else ""
            return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))
        except Exception:
            return u

    def _format_pic(self, pic_url):
        if not pic_url:
            return ""
        pic_url = str(pic_url).strip()
        # data: 判断必须在 _abs 之前：_abs 会把 data:... 拼成站内地址，之后再判就永不命中
        if not pic_url or pic_url.startswith("data:"):
            return ""
        if "/_next/image?" in pic_url:
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(pic_url).query)
                if "url" in q and q["url"]:
                    pic_url = urllib.parse.unquote(q["url"][0])
            except Exception:
                pass
            if not pic_url or pic_url.startswith("data:"):
                return ""
        pic_url = self._abs(pic_url)
        if "logo-huangguo.png" in pic_url or "fab-btn-bg.svg" in pic_url:
            return ""
        if "@Referer=" not in pic_url:
            return "%s@Referer=%s/" % (pic_url, self.site_url)
        return pic_url

    def _series_to_vod(self, s):
        """站内 API 的 series 对象 -> TVBox vod 卡片（popular/ranking/search 三处共用）。"""
        if not isinstance(s, dict):
            return None
        slug = str(s.get("slug") or "").strip()
        title = self._clean(s.get("title") or "")
        if not slug or not title:
            return None
        pic = self._format_pic(s.get("posterUrl") or s.get("cover_url") or "")
        remark = self._clean(s.get("episode_label") or "")
        if not remark:
            status = str(s.get("seriesStatus") or s.get("series_status") or "")
            total_ep = s.get("totalEpisodes") or s.get("episode_count")
            if status == "completed":
                remark = "已完结"
            elif total_ep:
                remark = "更新至%s集" % total_ep
        score = s.get("score")
        if score:
            try:
                sc = str(score)
                if isinstance(score, float):
                    sc = sc.rstrip("0").rstrip(".")
                sc_str = sc + "分"
                remark = ("%s · %s" % (sc_str, remark)) if remark else sc_str
            except Exception:
                pass
        return {
            "vod_id": self.site_url + "/drama/" + slug,
            "vod_name": title,
            "vod_pic": pic,
            "vod_remarks": remark,
        }

    def _extract_episodes(self, html):
        """从详情/播放页内嵌的 episodes 数据取 {集号: (集名, m3u8)}。不依赖 URL 里的 slug 形态，
        ser_ 形式与短 slug 形式的详情页都适用。"""
        eps = {}
        if not html:
            return eps
        for m in self._EP_RE.finditer(html):
            try:
                num = int(m.group(1))
            except Exception:
                continue
            url = self._clean_media_url(m.group(3))
            if not url or (".m3u8" not in url.lower() and ".mp4" not in url.lower()):
                continue
            if num in eps:
                continue
            title = self._clean(m.group(2)) or ("第%s集" % num)
            eps[num] = (title, url)
        return eps

    def _probe_media(self, url, timeout=8):
        """媒体门禁：m3u8 必须含 #EXTM3U，mp4 必须含 ftyp 或 video/* 类型；验不过返回 False。"""
        try:
            headers = dict(self.headers)
            headers["Range"] = "bytes=0-2047"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                head = resp.read(2048)
                ctype = (resp.headers.get("Content-Type") or "").lower()
            low = url.lower()
            if ".m3u8" in low:
                return b"#EXTM3U" in head
            if ".mp4" in low:
                return b"ftyp" in head[:32] or ctype.startswith("video/")
            return True
        except Exception:
            return False

    def getName(self):
        return self.site_name

    def homeContent(self, filter):
        # 榜单 3 个 + 标签 12 个：与首页实测一致（热门标签栏就是这 12 个 tag）
        classes = [
            {"type_id": "api:popular", "type_name": "热门推荐"},
            {"type_id": "api:latest", "type_name": "最新上架"},
            {"type_id": "api:top-rated", "type_name": "高分佳作"},
            {"type_id": self.site_url + "/tag/luanlun", "type_name": "乱伦"},
            {"type_id": self.site_url + "/tag/j", "type_name": "巨乳"},
            {"type_id": self.site_url + "/tag/mx", "type_name": "明星"},
            {"type_id": self.site_url + "/tag/xd", "type_name": "现代"},
            {"type_id": self.site_url + "/tag/ds", "type_name": "都市"},
            {"type_id": self.site_url + "/tag/hr", "type_name": "后入"},
            {"type_id": self.site_url + "/tag/m", "type_name": "魔改电视剧"},
            {"type_id": self.site_url + "/tag/kj", "type_name": "口交"},
            {"type_id": self.site_url + "/tag/sn", "type_name": "熟女"},
            {"type_id": self.site_url + "/tag/kb", "type_name": "口爆"},
            {"type_id": self.site_url + "/tag/d", "type_name": "大男主"},
            {"type_id": self.site_url + "/tag/qingc", "type_name": "清纯"}
        ]
        seen = set(c["type_id"] for c in classes)

        # 只探首页：/tags、/categories 实测 404，/popular 是 JS 空壳无链接，探了也白探
        html = self._fetch(self._abs("/"))
        if html:
            for m in re.finditer(r"href=[\x22\x27]([^\x22\x27\s]*?(?:/tag/|/category/|/channel/)[^\x22\x27\s]+)[\x22\x27][^>]*>(.*?)</a>", html, re.S | re.I):
                href, raw_name = m.group(1).strip(), m.group(2)
                name = self._clean(raw_name)
                if not name or len(name) > 15 or any(k in name for k in ("首页", "留言", "下载", "APP", "公告", "登录", "注册")):
                    continue
                tid = self._abs(href)
                if tid not in seen:
                    seen.add(tid)
                    classes.append({"type_id": tid, "type_name": name})

        return {"class": classes, "filters": {}}

    def _parse_cards(self, html):
        cards = []
        seen = set()

        blocks = re.findall(r"<a[^>]*class=[\x22\x27][^\x22\x27]*?hg-drama-card[^\x22\x27]*?[\x22\x27][^>]*>.*?</a>", html, re.S | re.I)
        if not blocks:
            blocks = re.findall(r"(<a[^>]*href=[\x22\x27][^\x22\x27]*?/drama/[^\x22\x27\s]+[\x22\x27][^>]*>.*?</a>)", html, re.S | re.I)
        if not blocks:
            blocks = [html]

        for blk in blocks:
            lm = re.search(r"href=[\x22\x27]([^\x22\x27\s]*?/drama/[^\x22\x27\s/]+)[\x22\x27]", blk, re.I)
            if not lm:
                continue

            href = lm.group(1)
            vid = self._abs(href)
            if vid in seen:
                continue
            seen.add(vid)

            title = ""
            tm = re.search(r"<h3[^>]*>(.*?)</h3>", blk, re.S | re.I)
            if tm:
                title = self._clean(tm.group(1))
            if not title:
                for am in re.finditer(r"alt=[\x22\x27]([^\x22\x27\n]+)[\x22\x27]", blk, re.I):
                    cand = self._clean(am.group(1))
                    if cand and cand != "Loading":
                        title = cand
                        break
            if not title or len(title) < 2:
                continue

            pic = ""
            pm_lazy = re.search(r"(?:data-src|data-original|data-lazy-src)=[\x22\x27]([^\x22\x27\s]+)[\x22\x27]", blk, re.I)
            if pm_lazy:
                pic = self._format_pic(pm_lazy.group(1))
            if not pic:
                for pm_src in re.finditer(r"src=[\x22\x27]([^\x22\x27\s]+)[\x22\x27]", blk, re.I):
                    cand = self._format_pic(pm_src.group(1))
                    if cand:
                        pic = cand
                        break

            remark = ""
            ep_m = re.search(r"hg-drama-card__episode[^>]*>(.*?)</span>", blk, re.S | re.I)
            if ep_m:
                remark = self._clean(ep_m.group(1))
            if not remark:
                st_m = re.search(r">(已完结|更新至\d+集)</div>", blk, re.I)
                if st_m:
                    remark = self._clean(st_m.group(1))

            sc_m = re.search(r"(\d+\.\d+)\s*(?:<!--\s*-->)?\s*分", blk, re.I)
            if sc_m:
                sc_str = sc_m.group(1) + "分"
                remark = ("%s · %s" % (sc_str, remark)) if remark else sc_str

            cards.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remark
            })
        return cards

    def homeVideoContent(self):
        html = self._fetch(self.site_url + self.entry_path)
        return {"list": self._parse_cards(html)[:24]}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        tid = str(tid or "")

        # 榜单走站内 API（实测：接口不认 page/offset，只回固定榜单，故 pg>1 返回空页）
        if tid in self._API_LISTS:
            if pg > 1:
                return {"list": [], "page": pg, "pagecount": pg, "limit": 0, "total": 0}
            data = self._fetch_json(self._abs(self._API_LISTS[tid]))
            items = []
            for it in (data or {}).get("data") or []:
                s = it.get("series") if isinstance(it, dict) else None
                if isinstance(s, dict):
                    v = self._series_to_vod(s)
                    if v:
                        items.append(v)
            return {
                "list": items,
                "page": pg,
                "pagecount": 1,
                "limit": len(items),
                "total": len(items)
            }

        # 标签页走 HTML（实测：服务端渲染，24 条/页，?page= 真分页，相邻页 0 重叠）
        url = self._abs(tid)
        if pg > 1:
            sep = "&" if "?" in url else "?"
            url = "%s%spage=%d" % (url, sep, pg)

        html = self._fetch(url)
        items = self._parse_cards(html)
        return {
            "list": items,
            "page": pg,
            "pagecount": pg + 1 if len(items) >= 8 else pg,
            "limit": len(items),
            "total": 0
        }

    def detailContent(self, ids):
        vid = str(ids[0]) if ids else ""
        url = self._abs(vid)
        html = self._fetch(url)

        title = ""
        tm = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        if tm:
            title = self._clean(tm.group(1))
        if not title:
            tm = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
            if tm:
                title = self._clean(tm.group(1).split("-")[0])

        pic = ""
        for pm in re.finditer(r"(?:og:image|content|src)=[\x22\x27]([^\x22\x27\s]+(?:/uploads/|/_next/image)[^\x22\x27\s]*)[\x22\x27]", html, re.I):
            cand = self._format_pic(pm.group(1))
            if cand:
                pic = cand
                break

        desc = ""
        dm = re.search(r"<meta[^>]*name=[\x22\x27]description[\x22\x27][^>]*content=[\x22\x27]([^\x22\x27]+)[\x22\x27]", html, re.I)
        if dm:
            desc = self._clean(dm.group(1))

        # 封面/标题/简介兜底：页面里取不到时走详情接口（slug 从 og:url 取短 slug，ser_ 链接也适用）
        if not pic or not title or not desc:
            slug = ""
            om = re.search(r"property=[\x22\x27]og:url[\x22\x27][^>]*content=[\x22\x27][^\x22\x27]*?/drama/([^\x22\x27/\s]+)", html, re.I)
            if om:
                slug = om.group(1)
            if slug:
                try:
                    dj = self._fetch_json(self._abs("/api/series/detail/" + urllib.parse.quote(slug)))
                    dd = (dj or {}).get("data") or {}
                    if not pic:
                        pic = self._format_pic(dd.get("posterUrl") or "")
                    if not title:
                        title = self._clean(dd.get("title") or "")
                    if not desc:
                        desc = self._clean(dd.get("summary") or dd.get("description") or "")
                except Exception:
                    pass

        # 选集优先走页面内嵌 episodes 数据（number/title/playUrl 直给 m3u8，不依赖 URL 里的 slug 形态）
        play_urls = []
        eps = self._extract_episodes(html)
        for num in sorted(eps):
            ep_title, ep_url = eps[num]
            play_urls.append("%s$%s" % (ep_title, ep_url))

        # 回落：页面上的 /drama/*/play/N 链接（不限 slug，避免 ser_ 链接取不到选集）
        if not play_urls:
            ep_map = {}
            for m in re.finditer(r"href=[\x22\x27]([^\x22\x27\s]*?/drama/[^/\x22\x27\s]+/play/(\d+))[\x22\x27]", html, re.I):
                try:
                    num = int(m.group(2))
                except Exception:
                    continue
                if num not in ep_map:
                    ep_map[num] = self._abs(m.group(1))
            for num in sorted(ep_map):
                play_urls.append("第%s集$%s" % (num, ep_map[num]))

        vod = {
            "vod_id": vid,
            "vod_name": title or "未知",
            "vod_pic": pic,
            "vod_content": desc,
            "vod_play_from": "黄果短剧",
            "vod_play_url": "#".join(play_urls)
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        raw = str(id)
        url = raw.rsplit("$", 1)[-1] if "$" in raw else raw
        url = url.strip()

        # 直给媒体地址（详情 episodes 直包的 m3u8 走这条）：清洗后验门禁，验不过回落 parse=1
        if ".m3u8" in url.lower() or ".mp4" in url.lower():
            url = self._clean_media_url(url if url.startswith("http") else self._abs(url))
            if url and self._probe_media(url):
                return {"parse": 0, "playUrl": "", "url": url, "header": self.headers}
            return {"parse": 1, "playUrl": "", "url": url, "header": self.headers}

        url = self._abs(url)
        html = self._fetch(url)
        play = ""

        # 先按集数从内嵌 episodes 数据取对应 m3u8（页面含全部集数的 playUrl，取首个会串集）
        ep_num = None
        nm = re.search(r"/play/(\d+)", url)
        if nm:
            try:
                ep_num = int(nm.group(1))
            except Exception:
                ep_num = None
        eps = self._extract_episodes(html)
        if eps:
            if ep_num is not None and ep_num in eps:
                play = eps[ep_num][1]
            elif eps:
                play = eps[sorted(eps)[0]][1]

        if not play:
            for pat in (
                r"<source[^>]+src=[\x22\x27]([^\x22\x27\s]+)[\x22\x27]",
                r"<video[^>]+src=[\x22\x27]([^\x22\x27\s]+)[\x22\x27]",
                r"[\x22\x27](https?://[^\x22\x27\s]+\.m3u8[^\x22\x27\s]*)[\x22\x27]",
                r"[\x22\x27](https?://[^\x22\x27\s]+\.mp4[^\x22\x27\s]*)[\x22\x27]",
                r"[\x22\x27](/uploads/[^\x22\x27\s]+\.(?:m3u8|mp4)[^\x22\x27\s]*)[\x22\x27]"
            ):
                m = re.search(pat, html, re.I)
                if m:
                    play = self._clean_media_url(m.group(1))
                    if play.startswith("/"):
                        play = self._abs(play)
                    break

        if play and self._probe_media(play):
            return {"parse": 0, "playUrl": "", "url": play, "header": self.headers}

        return {"parse": 1, "playUrl": "", "url": url, "header": self.headers}

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        kw = urllib.parse.quote(str(key or "").strip())
        if not kw:
            return {"list": [], "page": pg, "pagecount": pg, "limit": 0, "total": 0}
        # 实测：搜索走 /api/search（/search?q= 等 HTML 页是 JS 空壳，0 结果）
        data = self._fetch_json(self._abs("/api/search?q=%s&page=%d" % (kw, pg)))
        items = []
        for s in (data or {}).get("results") or []:
            if isinstance(s, dict):
                v = self._series_to_vod(s)
                if v:
                    items.append(v)
        try:
            total = int((data or {}).get("total") or 0)
        except Exception:
            total = 0
        has_more = bool((data or {}).get("has_more"))
        return {
            "list": items,
            "page": pg,
            "pagecount": pg + 1 if has_more else pg,
            "limit": len(items),
            "total": total
        }

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(m3u8|mp4|mp3|m4a|flv)(\?|$)", str(url or ""), re.I))

    def manualVideoCheck(self):
        return False

    def localProxy(self, params):
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {}
        if not isinstance(params, dict):
            params = {}

        t = params.get("type", "")
        if t == "pic":
            url = urllib.parse.unquote(params.get("url", ""))
            if not url or url.startswith("http://127.0.0.1"):
                return [404, "text/plain", b""]
            content = b""
            try:
                if self.session:
                    r = self.session.get(url, headers=self.headers, timeout=10,
                                         proxies=self.session.proxies or None)
                    if r.status_code == 200:
                        content = r.content
                if not content:
                    req = urllib.request.Request(url, headers=self.headers)
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        content = resp.read()
            except Exception:
                return [404, "text/plain", b""]

            if not content:
                return [404, "text/plain", b""]

            if content[:3] == b"\xff\xd8\xff":
                return [200, "image/jpeg", content]
            elif content[:8] == b"\x89PNG\r\n\x1a\n":
                return [200, "image/png", content]
            elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
                return [200, "image/webp", content]
            elif content[:3] == b"GIF":
                return [200, "image/gif", content]
            return [200, "application/octet-stream", content]

        return [404, "text/plain", b""]

    def destroy(self):
        try:
            if self.session:
                self.session.close()
        except Exception:
            pass
