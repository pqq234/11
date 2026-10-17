/*
@header({
  searchable: 2,
  filterable: 1,
  quickSearch: 1,
  title: '短剧库',
  '类型': '短剧',
  lang: 'ds'
})
*/

// 主分类 = 平台（红果/黄豆/黄果），子分类 = 各平台自己的分类（filter 按主分类 id 分组）
var filter_def = 'H4sIAAAAAAAC/60aWVMTzfa/8CwlSUgCPl0ffbhV98mXW1/dGkhMBmGCSUbAr6yCL6zKFkEWiSA7yCIIaiBE/sz0zORf3DOZXk4PQyCSKrSq+5zpPvvW+bspmdISCT3V9OS/fze9jA80PWnqVLJNj5o0pScOCzI+ap2WYP1a6dbjVSwNts3BkpU7Mj8cmTsFBwhbaUV72ZxMZZvePnJxrMKacXlJJnY9OOm40s2RzKuDmxidqR61k6M8fXYTQ1FvXsPgcHxzLK30KJ5LKLx6uAehegWFKyoD/vX2r0dNfXE1oStanfIhI3uV3B47sbubHpaMw7n1nWR9/10ZnKAndalaot+hhhFOZrbszREKTehvkgBMcGhlbMqaX2N8O5rOJOMITo5/kssjfraSVRHQHHpvjZ9SYLeqaI7Mq1xkkoqWhFUjGQEVmifzXIXaK6Fgc+FEaKdf1bp0ofv5Ajn+QkFZoLHKpOB/cNTeYPxpar84k1xd2oMjZGWVlD9Q+Cv4PPEmGRc422PkosShSUnuW1NGaYzCXuhwrSDKKB6RlbK5sUPBb6iL9dwtetdIlNTLug3O9UbsBR2pGFCMhFVDjub4krW9yulVNMdOhJS3V+3TrxTqQIBCDCSTJQQcUO+rHvvHEtm/5rfqaj/S7P61/fOdx4CBnwEdKejqHztXptABVcPytZdnwYCZ6vW4Y8BI+AfmwiI5HoH/me8AYTGkRGt6WCjfsVRX/VUFdShqTH9IQHgFZ3Xo9xJhJVcmxX8oLKZnkki60ydGadPeGzRzI1yrihZT1AEF/AcbWw1B3e4jd2gPUoC9OcS0B5BOFJTt2Uly/JkCHcPvQCZT29puVw6gqpKOatllTQOoLH4l+5/4l452tbtUf7dh+kXYi3PQEZduVTueGGBc7Vizo3Ik6Na1bhUHea+iE7qPms2jHeP3F/jfnJijeH06mEQfIN/L6SqfP5hL2+aXdbJyxOMeKBakA8ekBoQLQPhIDNSbyiD6kMIl4xSCJs5V9whgxtUnkl8yinPG5QHFAvoHsHbMpTVIMmS7LEU6OdXUiIOVpTMyMiHRCUJOJNysWuX8ldqj1F0tTe/ZU7P0wBZ/QpoDHp8HZZvDzMQCwWjIP+kDJOgfLcLRgMemjdIyGAj/sC3in+vCUUGjcbFufs4zQDsi/iQPWY5/EfI3+TAm7qZ1AQ1tHvOlkBAmfjePiGtvFV8UDoziAgOEI6iamDQP18lITtzT7h/xWltaPK7NCQj5Z/toe1h8cVaySkxH0baooOxzzj55z79o8S/Jom2tSANn5uCuOT5b+XjNqca8TszZw0UnqhWZcKOBiH9Ea21rqVXptLYIpdjXZbJTsoYO7PyhMPpoIOxfqUSQaVT2D63571z6QpH20CQ6KtjqCe1MwK1CwJWDJXPivVF8T05PBfNCZWTv1LiYNZemwb8FPOyf4KLBKLpxBN8o+DZXrm0eRaKBIDYC44KVbqGQ4Ip8HIXExe8IIfMElZ5YpRnAEMQFUNhCAR4g6Mut3xDT7G+fKxtLAi4kbI+dk2+TTGvtgkgy9IvMHpLrHNk84R9iDQznzXOWYcNBYSaQLyuLe1LqjiAFSWk7hBxKStlhJGDovsjQGJnKVcZYlGhD0pSyTSjiX/IEgpF2/6QeQpo8mYEewZrYF4JC4WtlQ5Qq4VZhGObhBlkokNEtsGImx4jkdKTI+I0ExG2VuZ9kJi+uQnSM/LCmmWcH2/zrDeSYUhUVFFZh/nNoLbAbkEDN2VXrMM8jBzKWoR9g5iKgRWlCikGvCtmpznZh/FQUE4oqlRE1Ss7a7aZUodyoQWt0U24Lb+0O8rIkrkEP2K/q/uJy0jluM8p5kUf7gKIub0njKWZ4EfOiAY393VK7hYa6y3jXeVnlozgNJUpRu2DMRpFJOKZor0E99yjzfRJLTHGqZaegVfyTo2jFeDXo/GvoRAAKQsFtOo6Z9avgqoQMqD2NHUvUmCDUmAD4jk7uO5OZ2apsTnMXe4FhtRrFms5XwzhrORaZHiUz3zkf1c/coZjuEl2nqHEodCOYn5ilohCswF4f9CvjXL/xS5tuvySlYlq6/4GRSs1AwN8EQ54uhkV1T1vCgrqn3WBpi1L5Uu+rt7+wJgtG+YuZO7MKPAMhcUCKzp9JET+AGFk5J1ufwAtIWaRWQWGhWBmac+sF69OwE6W58QZCnjRPynOAzKCtePwKf26laf/6xhC8Jabc8ESoODRVh7+HRGlsMeAldJcucGbjMLrwdQO68PUsuhBdyHchcrrwHTLQha/N0wWn5d2eUWajcLrgMKh0uE3Sha+b0wX/bnTFuGSGQxe3dVJiLQqin0ZpwRnRc16lLZ5r9bprlLKvi+EoEvEPIeFa2TXgr7xWf90EQ7XmMNxMM24p1AgzhTxe2chLOUTakot8SbHSltyQS/lb2pKLO2lGIG3JIpVkJ22J86bs8iE/qbrgZ4yXzQWWPemCw9bQGIguWNrpe1AkoAthSb9AquwidyErQRL/vXxeqqPoQvjuKble5L5bXfiaL134lgR04VuG0IVv504X94oHuFSnC/o04Ri5M4Kt+7VQvN9JRfPRvDl/IWA9qQQqlczZgnW+IaCZuJLuTArw/E97cUaAXyivU2k1i94Hjiet0hxCUDWoYTysBOvkpbKzUFn/wYpwqMHRI6Jkuc47ojy/fPpMeogEhB75gWanQKY+omdOqFYymNz632nd6laaP6bj8AIK1XQMjdEG7eu8UXwHRQ0rdeN98Uy2cawBfGoD2gwBdxiSZvJPn7nWgI6QrMHvvTnzGD84u2x6MXz4LRfIuxUvXm8qG9fgmaPbI/FgozpE+3rVKh35pbR/P39cWTuDCZcABnA4tCbGbpSUsGce/7iRu1xdQlEndKn3xpRsPIPE9MFen5TZR6+PlO1Ud6xezygNm6sFMr1GxlfYq5HS0dyCjWB81ikhsS05KIEbKJI1OSjB2+zEAYYw7V11R6fCoBDWv8DyWTMZ/4PfRWBPYwOarnDgIQHT0Q/Wr9t6iKakSjEFhwMe+See8K1bnNnB4Vti3udoAWHQDVESe25hd1Q57nSaw/qFJx3qPOt0en7OgPXuSRXYXuTQ4w6X5MnS7YHNE9ckZ+5Ip/oyYubh2JqqNCAi4xjmXijpN5uMg/+mUTPpjMGleAoXP5G2+XHlU3t3VBKcgytto9bC6dSKRXN8BuPi7VqvoIArbcuPJNKIvoqLt3m7US01jetj0BrClbblelV6aanSi7elmKY8xJlvppEHmKsnXfoZrGSXDTHbRz7hzoU1i6D30mGh4w/MWgopzeGu/k4VZeajTXt3WMLRUukepft/mWQqnfWEHZm3mN6dZWg0nrYHHkKd92cxd2nihhoQhuNFvE2A+VivqnnyLIX1Kqr03O3RoCNx5wdIT4Qqq7z2xIItrW11cus5Gz5pDqLnz8uSfTrqGu/TZwgn4kExrr6Qrx8QgjjDLI5Yl98IPAFvnyEENBF6+hx+BgVdHTlaJBcfMSXo0aZsXO7aY1/N91P4ECTADRu6pK1d8fTkIIhipz1wAxjFg1Yys2mf5MyPy/h41Ocvl+3laXKwT3YuMIVB7y80Lk7hDQ9joJfLUt5cWCazOWuugG9Bb5dVGFn5LRre3lQmm/E4q2RJ4heDrjWktHijqlAyMmWfM3ZfpOMiMDx/9p/H1u43OJBCX6u9bLqR0rv0htXB951bNHoecd+5SnXAI72RSlv1zlV8RlDSljwvkaZe0pb8giD9/kLaclT29v97p25u2SsAAA==';;;;;

var rule = {
    title: '短剧库',
    host: 'http://127.0.0.1:8998',
    homeUrl: 'http://127.0.0.1:8998/api/home?plat=hongguo&page=1',
    searchUrl: 'http://127.0.0.1:8998/api/search?wd=**&plat=fyclass&page=fypage',
    url: 'http://127.0.0.1:8998/api/category?plat=fyclass&page=fypage',
    filter_url: 'cat={{fl.cat}}',
    class_name: '红果&围观&河马&山海&好看&百度&星芽&七猫&大芒&西饭&星星&薏米&悟圣&七星&酷我&牛牛&喜福&爽爽&五五&黄豆&黄豆2&黄果&黄果2&黄果旧版&黄剧&野果&51短剧&橙果&香蕉&黄瓜&狂飙&91短剧&2048短剧&短剧one&搜剧AI&一直看&爱优影视&剧屋',
    class_url: 'hongguo&weiguan&hema&shanhai&haokan&baidu&xingya&qimao&damang&xifan&xingxing&yimi&wusheng&qixing&kuwo&niuniu&xifu&shuang&wuwu&huangdou&huangdou2&huangguo&huangguo2&huangguoold&huangju&yeguo&dj51&chengguo&xiangjiao&huanggua&kuangbiao&dj91&md2048&duanjuone&souju&yizk&iuzvod&juwu',
    filter: filter_def,
    filterable: 1,
    headers: {
        'User-Agent': 'MOBILE_UA'
    },
    timeout: 15000,
    multi: 1,
    searchable: 2,
    play_parse: true,
    推荐: 'json:data.list;vod_name;vod_pic;vod_remarks;vod_id;vod_content',
    一级: 'json:data.list;vod_name;vod_pic;vod_remarks;vod_id;vod_content',
    搜索: 'json:data.list;vod_name;vod_pic;vod_remarks;vod_id;vod_content',
    二级: async function () {
        let id = String(this.vid || this.orId || '').trim();
        if (!id) {
            id = String(this.input || '').split('?')[0].split('/').pop();
        }
        let platKey = '';
        let platName = '短剧库';
        // 平台名表：顺序与 class_name / class_url 一致，跟 Go 侧 platformOrder 同步
        const PLAT_NAMES = {
            hongguo: '红果', weiguan: '围观', hema: '河马', shanhai: '山海',
            haokan: '好看', baidu: '百度', xingya: '星芽', qimao: '七猫',
            damang: '大芒', xifan: '西饭', xingxing: '星星', yimi: '薏米',
            wusheng: '悟圣', qixing: '七星', kuwo: '酷我', niuniu: '牛牛', xifu: '喜福', shuang: '爽爽',
            wuwu: '五五', huangdou: '黄豆', huangdou2: '黄豆2', huangguo: '黄果',
            huangguo2: '黄果2', huangguoold: '黄果旧版', huangju: '黄剧',
            yeguo: '野果', dj51: '51短剧', chengguo: '橙果', xiangjiao: '香蕉',
            huanggua: '黄瓜', kuangbiao: '狂飙', dj91: '91短剧', md2048: '2048短剧',
            duanjuone: '短剧one', souju: '搜剧AI', yizk: '一直看',
            iuzvod: '爱优影视', juwu: '剧屋'
        };
        let colonIdx = id.indexOf(':');
        if (colonIdx > 0) {
            platKey = id.substring(0, colonIdx);
            if (PLAT_NAMES[platKey]) platName = PLAT_NAMES[platKey];
        }
        let api = 'http://127.0.0.1:8998/api/detail?id=' + encodeURIComponent(id);
        let html = JSON.parse(await request(api));
        let d = html.data || {};
        let base_vod = {
            vod_id: id,
            vod_name: d.vod_name || '',
            type_name: d.vod_class || '',
            vod_pic: d.vod_pic || '',
            vod_content: d.vod_content || ''
        };
        let playUrls = [];
        for (let ep of (d.episodes || [])) {
            playUrls.push((ep.name || ('第' + ep.no + '集')) + '$' + ep.url);
        }
        base_vod.vod_play_from = platName;
        base_vod.vod_play_url = playUrls.join('#');
        return base_vod;
    },
    lazy: async function () {
        let {input} = this;
        let playPage = String(input || '').trim();
        if (!playPage) {
            return {parse: 0, url: ''};
        }
        let api = 'http://127.0.0.1:8998/api/play?url=' + encodeURIComponent(playPage);
        let res = JSON.parse(await request(api));
        if (res && res.code === 200 && res.data && res.data.url) {
            return {parse: 0, url: res.data.url};
        }
        return {parse: 0, url: playPage};
    }
};