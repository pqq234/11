# -*- coding: utf-8 -*-
"""
夜社(yeshe.tv) TVBox / OK影视 / 影视仓 标准 Python 源。

修复要点(2026-11-27):
1. 原版 detailContent 自己拼 m3u8: 写死的 CDN 域名 vods3.epobwsreb383eyq2bi.com 已轮换失效,
   且分集路径不是 /<集数>/ 而是 /<集数+随机后缀>/ (如 /1kzbam/), 拼出来的地址必 404。
   改为: 详情只给每集的播放页路径, playerContent 打开播放页读 player_aaaa 的真实 url。
2. 域名解析结果缓存, 不再每个请求都去跳一次短链接; 请求失败时自动重新解析并重试一次。
3. player_aaaa 的 encrypt 兼容 0/1/2 三种。
"""
import sys, json, re, base64
from urllib.parse import quote, parse_qs, unquote

sys.path.append('..')

try:
    from base.spider import Spider as _Spider
except ImportError:
    import requests as rq

    class _Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = rq.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r


class Spider(_Spider):
    host = 'https://yeshe.tv'
    short_url = 'https://ysurl.win/755WwN'

    header = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Referer': 'https://yeshe.tv/',
    }

    # ------------------------------------------------------------
    #  基础方法 (TVBox 框架必需)
    # ------------------------------------------------------------
    def getName(self):
        return '夜社'

    def init(self, extend=''):
        if isinstance(extend, list):
            self.extend = ''
        else:
            self.extend = extend or ''
        self._domain = ''
        self._get_domain()

    def isVideoFormat(self, url):
        return any(x in url for x in ['.m3u8', '.mp4', '.flv', '.avi', '.mkv'])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ------------------------------------------------------------
    #  域名解析 (短链接跳转镜像站, 结果缓存, 失败才重解析)
    # ------------------------------------------------------------
    def _resolve_domain(self):
        if self.extend and self.extend.startswith('http'):
            dm = re.match(r'(https?://[^/]+)', self.extend)
            return dm.group(1).rstrip('/') if dm else self.extend.rstrip('/')
        try:
            r = self.fetch(self.short_url, headers=self.header, allow_redirects=False, timeout=15)
            loc = r.headers.get('Location', '') if hasattr(r, 'headers') else ''
            if loc:
                dm = re.match(r'(https?://[^/]+)', loc)
                if dm:
                    return dm.group(1).rstrip('/')
        except Exception:
            pass
        return self.host

    def _get_domain(self):
        if not self._domain:
            self._domain = self._resolve_domain()
        return self._domain

    # ------------------------------------------------------------
    #  内部请求
    # ------------------------------------------------------------
    def _fetch_html(self, path):
        last_err = None
        for attempt in range(2):
            try:
                url = path if path.startswith('http') else self._get_domain() + path
                r = self.fetch(url, headers=self.header, timeout=15)
                text = r.text if hasattr(r, 'text') else r.content.decode('utf-8', errors='ignore')
                return self._decode_page(text)
            except Exception as e:
                last_err = e
                self._domain = ''  # 域名可能已失效, 下一轮重新解析
        raise last_err

    # ------------------------------------------------------------
    #  页面解密 (base64 混淆)
    # ------------------------------------------------------------
    @staticmethod
    def _decode_page(text):
        b64 = re.search(r'var\s+a\s*=\s*"([A-Za-z0-9+/=]+)"', text)
        if b64:
            try:
                dec = base64.b64decode(b64.group(1)).decode('utf-8', errors='replace')
                if len(dec) > len(text) * 0.3:
                    return dec
            except Exception:
                pass
        return text

    # ------------------------------------------------------------
    #  分类列表
    # ------------------------------------------------------------
    classes = [
        {'type_id': '2', 'type_name': '视频'},
        {'type_id': '13', 'type_name': 'AI短剧'},
        {'type_id': '36', 'type_name': '擦边短剧'},
        {'type_id': '11', 'type_name': '国产视频'},
        {'type_id': '12', 'type_name': '日本AV'},
        {'type_id': '14', 'type_name': '欧美无码'},
        {'type_id': '35', 'type_name': '韩国BJ'},
        {'type_id': '1', 'type_name': '动漫'},
        {'type_id': '7', 'type_name': '同人作品'},
        {'type_id': '8', 'type_name': '动画卡通'},
        {'type_id': '10', 'type_name': '3D动漫'},
        {'type_id': '9', 'type_name': '中文动漫'},
        {'type_id': '32', 'type_name': '里番'},
        {'type_id': '33', 'type_name': '泡面番'},
        {'type_id': '3', 'type_name': '有声'},
        {'type_id': '15', 'type_name': '有声小说'},
        {'type_id': '16', 'type_name': '淫词艳曲'},
        {'type_id': '17', 'type_name': '激情骚麦'},
        {'type_id': '5', 'type_name': '写真'},
        {'type_id': '20', 'type_name': '秀人系列'},
        {'type_id': '22', 'type_name': '网红COS'},
        {'type_id': '21', 'type_name': '机构套图'},
        {'type_id': '23', 'type_name': '内购私拍'},
        {'type_id': '34', 'type_name': 'AI绘图'},
        {'type_id': '24', 'type_name': '各国套图'},
    ]

    # ------------------------------------------------------------
    #  首页
    # ------------------------------------------------------------
    def homeContent(self, filter):
        return {'class': self.classes, 'filters': {}}

    def homeVideoContent(self):
        try:
            html = self._fetch_html('/type/13.html')
            return {'list': self._parse_cards(html)[:30]}
        except Exception:
            return {'list': []}

    # ------------------------------------------------------------
    #  分类内容
    # ------------------------------------------------------------
    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        try:
            url = '/type/%s-%d.html' % (tid, pg) if pg > 1 else '/type/%s.html' % tid
            html = self._fetch_html(url)
            return {
                'page': pg,
                'pagecount': 999,
                'limit': 120,
                'total': 99999,
                'list': self._parse_cards(html),
            }
        except Exception:
            return {'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0, 'list': []}

    # ------------------------------------------------------------
    #  详情页: 只给每集播放页路径, 真实地址在 playerContent 里现取
    # ------------------------------------------------------------
    def detailContent(self, ids):
        try:
            vod_id = ids[0] if isinstance(ids, list) else str(ids)
            html = self._fetch_html('/play/%s/1/1.html' % vod_id)

            config = self._extract_json(html, 'player_aaaa')
            if not config:
                return {'list': []}

            vod_data = config.get('vod_data', {})
            vod_pic = vod_data.get('vod_pic', '')
            vod_name = vod_data.get('vod_name', '')
            vod_class = vod_data.get('vod_class', '')

            ep_count = 1
            ep_m = re.search(r'vod_play_all\s*=\s*(\d+)', html)
            if ep_m:
                ep_count = int(ep_m.group(1))
            else:
                eps = set(re.findall(r'/play/%s/1/(\d+)\.html' % vod_id, html))
                ep_count = len(eps) if eps else 1

            play_urls = []
            for i in range(1, ep_count + 1):
                play_urls.append('第%d集$/play/%s/1/%d.html' % (i, vod_id, i))

            vod = {
                'vod_id': vod_id,
                'vod_name': vod_name,
                'vod_pic': vod_pic,
                'type_name': vod_class,
                'vod_year': '',
                'vod_area': '',
                'vod_actor': '',
                'vod_director': '',
                'vod_content': '',
                'vod_remarks': '%d集' % ep_count,
                'vod_play_from': '夜社',
                'vod_play_url': '#'.join(play_urls),
            }
            return {'list': [vod]}
        except Exception:
            return {'list': []}

    # ------------------------------------------------------------
    #  搜索
    # ------------------------------------------------------------
    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        try:
            url = '/vod/search/wd/%s.html' % quote(key)
            if pg > 1:
                url = '/vod/search/wd/%s-%d.html' % (quote(key), pg)
            html = self._fetch_html(url)
            return {'page': pg, 'list': self._parse_cards(html)[:30]}
        except Exception:
            return {'page': 1, 'list': []}

    def searchContentPage(self, key, quick, pg=1):
        return self.searchContent(key, quick, pg)

    # ------------------------------------------------------------
    #  播放: 打开该集播放页, 读 player_aaaa 的真实 url
    # ------------------------------------------------------------
    def playerContent(self, flag, id, vipFlags):
        play_id = str(id or '')
        headers = {'User-Agent': self.header['User-Agent'],
                   'Referer': self._get_domain() + '/'}
        try:
            if play_id.startswith('http') and ('.m3u8' in play_id or '.mp4' in play_id or '.mp3' in play_id):
                return {'parse': 0, 'url': play_id, 'header': headers}
            if play_id.startswith('/play/'):
                html = self._fetch_html(play_id)
                if html:
                    config = self._extract_json(html, 'player_aaaa')
                    if config and config.get('url'):
                        return {'parse': 0, 'url': self._decode_url(config), 'header': headers}
            return {'parse': 0, 'url': play_id, 'header': headers}
        except Exception:
            return {'parse': 0, 'url': play_id, 'header': headers}

    @staticmethod
    def _decode_url(config):
        url = config.get('url', '')
        enc = str(config.get('encrypt', '0'))
        try:
            if enc == '1':
                url = unquote(url)
            elif enc == '2':
                url = base64.b64decode(url).decode('utf-8', errors='ignore')
        except Exception:
            pass
        return url

    # ------------------------------------------------------------
    #  本地代理 (TVBox 框架调用)
    # ------------------------------------------------------------
    def localProxy(self, param):
        try:
            if isinstance(param, str):
                param_dict = parse_qs(param)
            else:
                param_dict = param

            do = param_dict.get('do', '')
            if isinstance(do, list):
                do = do[0] if do else ''

            if do == 'img':
                url = param_dict.get('url', '')
                if isinstance(url, list):
                    url = url[0] if url else ''
                if url:
                    try:
                        url = base64.urlsafe_b64decode(url).decode('utf-8')
                    except Exception:
                        pass
                    if url:
                        headers = {
                            'User-Agent': self.header['User-Agent'],
                            'Referer': self.host + '/',
                            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                        }
                        r = self.fetch(url, headers=headers, timeout=15)
                        ct = ''
                        if hasattr(r, 'headers'):
                            ct = r.headers.get('Content-Type', '')
                        if not ct or 'image' not in ct:
                            if '.png' in url:
                                ct = 'image/png'
                            elif '.webp' in url:
                                ct = 'image/webp'
                            elif '.gif' in url:
                                ct = 'image/gif'
                            else:
                                ct = 'image/jpeg'
                        content = r.content if hasattr(r, 'content') else r.text.encode('utf-8')
                        return [200, ct, content, {}]
        except Exception:
            pass
        return [404, 'text/plain', '', {}]

    # ------------------------------------------------------------
    #  工具方法
    # ------------------------------------------------------------
    def _extract_json(self, html, key):
        idx = html.find(key)
        if idx < 0:
            return None
        brace_start = html.find('{', idx)
        if brace_start < 0:
            return None
        depth = 0
        for i in range(brace_start, len(html)):
            c = html[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[brace_start:i + 1])
                    except Exception:
                        return None
        return None

    def _wrap_pic(self, pic_url):
        if not pic_url:
            return ''
        pic_url = pic_url.strip().strip('"\'')
        if pic_url.startswith('//'):
            pic_url = 'https:' + pic_url
        elif not pic_url.startswith(('http://', 'https://')):
            if pic_url.startswith('/'):
                pic_url = self._get_domain() + pic_url
            else:
                pic_url = self._get_domain() + '/' + pic_url
        return pic_url

    # ------------------------------------------------------------
    #  卡片解析
    # ------------------------------------------------------------
    def _parse_cards(self, html):
        vod_list = []
        seen = set()
        pattern = r'<a\s+href="/play/(\d+)/\d+/\d+\.html"\s*title="([^"]*)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, html, re.DOTALL)

        for vid, name, block in matches:
            if vid in seen:
                continue
            seen.add(vid)

            pic_url = ''
            cover_m = re.search(r'src="(https://[^"]*\.(?:webp|avif|png|jpg|jpeg))"', block)
            if cover_m:
                pic_url = cover_m.group(1)
            pic_url = self._wrap_pic(pic_url)

            remark = ''
            time_m = re.search(r'<div class="time">([^<]+)</div>', block)
            if time_m:
                remark = time_m.group(1).strip()

            vod_list.append({
                'vod_id': vid,
                'vod_name': name.strip(),
                'vod_pic': pic_url,
                'vod_remarks': remark,
            })
        return vod_list
