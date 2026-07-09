from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class RecruitingSource:
    name: str
    aliases: tuple[str, ...]
    url: str
    source_type: str
    industry: str
    company_type: str
    trust_level: str = "S"
    priority: int = 80
    parser_type: str = "generic"
    title: str = "官方招聘入口"


SOURCES: tuple[RecruitingSource, ...] = (
    RecruitingSource("国家能源集团", ("国家能源集团", "国家能源投资集团", "中国能源集团", "国能集团", "chnenergy"), "https://zhaopin.chnenergy.com.cn/", "official_company", "能源电力", "央企", priority=100, parser_type="chnenergy", title="国家能源集团人力资源招聘系统"),
    RecruitingSource("国家能源集团", ("国家能源集团", "国家能源投资集团", "中国能源集团", "国能集团", "chnenergy"), "https://zhaopin.chnenergy.com.cn/recTypeSerch?kinds=1", "official_company", "能源电力", "央企", priority=99, parser_type="chnenergy", title="国家能源集团校园招聘岗位"),
    RecruitingSource("国家能源集团", ("国家能源集团", "国家能源投资集团", "中国能源集团", "国能集团", "chnenergy"), "https://zhaopin.chnenergy.com.cn/annc/annclist?ggtype=1", "official_company", "能源电力", "央企", priority=98, parser_type="chnenergy", title="国家能源集团招聘公告"),
    RecruitingSource("国家电网", ("国家电网", "国家电网公司", "sgcc"), "https://zhaopin.sgcc.com.cn/", "official_company", "能源电力", "央企", priority=96, title="国家电网招聘平台"),
    RecruitingSource("中国南方电网", ("中国南方电网", "南方电网", "csg"), "https://zhaopin.csg.cn/", "official_company", "能源电力", "央企", priority=95, title="中国南方电网招聘系统"),
    RecruitingSource("中国大唐集团", ("中国大唐集团", "中国大唐", "大唐集团"), "https://zhaopin.china-cdt.com/", "official_company", "能源电力", "央企", priority=94, title="中国大唐集团招聘系统"),
    RecruitingSource("中国电建", ("中国电建", "中国电力建设集团", "powerchina"), "https://zhaopin.powerchina.cn/", "official_company", "能源建设", "央企", priority=94, title="中国电建招聘平台"),
    RecruitingSource("中国能建", ("中国能建", "中国能源建设集团", "ceec"), "https://ceec.iguopin.com/", "official_company", "能源建设", "央企", priority=94, title="中国能建招聘平台"),
    RecruitingSource("中国石化", ("中国石化", "中石化", "sinopec"), "https://job.sinopec.com/", "official_company", "能源化工", "央企", priority=93, title="中国石化人才招聘"),
    RecruitingSource("中国石油", ("中国石油", "中石油", "cnpc"), "https://zhaopin.cnpc.com.cn/", "official_company", "能源化工", "央企", priority=93, title="中国石油高校毕业生招聘"),
    RecruitingSource("中粮集团", ("中粮集团", "中粮", "cofco"), "https://cofco.zhiye.com/", "official_company", "食品农业", "央企", priority=92, title="中粮集团招聘"),
    RecruitingSource("中国广核集团", ("中国广核集团", "中广核", "cgn"), "https://cgn.hotjob.cn/", "official_company", "能源电力", "央企", priority=92, title="中广核招聘"),
    RecruitingSource("中国航天科工", ("中国航天科工", "航天科工", "casic"), "https://casic.zhiye.com/", "official_company", "航空航天", "央企", priority=91, title="中国航天科工招聘"),
    RecruitingSource("中国中车", ("中国中车", "中车集团", "crrc"), "https://crrc.zhiye.com/", "official_company", "轨道交通", "央企", priority=90, title="中国中车招聘"),
    RecruitingSource("中国移动", ("中国移动", "移动集团", "cmcc"), "https://job.10086.cn/", "official_company", "通信", "央企", priority=90, title="中国移动招聘"),
    RecruitingSource("中国电信", ("中国电信", "电信集团"), "https://job.chinatelecom.com.cn/", "official_company", "通信", "央企", priority=90, title="中国电信招聘"),
    RecruitingSource("字节跳动", ("字节跳动", "字节", "bytedance"), "https://jobs.bytedance.com/campus", "official_company", "互联网", "民企", priority=95, title="字节跳动校园招聘"),
    RecruitingSource("腾讯", ("腾讯", "tencent"), "https://join.qq.com/", "official_company", "互联网", "民企", priority=95, title="腾讯校园招聘"),
    RecruitingSource("阿里巴巴", ("阿里巴巴", "阿里", "alibaba"), "https://talent.alibaba.com/", "official_company", "互联网", "民企", priority=95, title="阿里巴巴招聘"),
    RecruitingSource("京东", ("京东", "jd.com", "jd"), "https://campus.jd.com/", "official_company", "互联网电商", "民企", priority=94, title="京东校园招聘"),
    RecruitingSource("美团", ("美团", "meituan"), "https://zhaopin.meituan.com/", "official_company", "互联网", "民企", priority=94, title="美团招聘"),
    RecruitingSource("华为", ("华为", "huawei"), "https://career.huawei.com/", "official_company", "通信科技", "民企", priority=94, title="华为招聘"),
    RecruitingSource("百度", ("百度", "baidu"), "https://talent.baidu.com/", "official_company", "互联网", "民企", priority=93, title="百度招聘"),
    RecruitingSource("快手", ("快手", "kuaishou"), "https://campus.kuaishou.cn/", "official_company", "互联网", "民企", priority=93, title="快手校园招聘"),
    RecruitingSource("网易", ("网易", "netease"), "https://game.campus.163.com/", "official_company", "互联网游戏", "民企", priority=92, title="网易校园招聘"),
    RecruitingSource("小米", ("小米", "xiaomi"), "https://xiaomi.jobs.f.mioffice.cn/", "official_company", "消费电子", "民企", priority=92, title="小米招聘"),
    RecruitingSource("拼多多", ("拼多多", "pdd"), "https://careers.pddglobalhr.com/", "official_company", "互联网电商", "民企", priority=92, title="拼多多招聘"),
    RecruitingSource("小红书", ("小红书", "xiaohongshu"), "https://job.xiaohongshu.com/", "official_company", "互联网", "民企", priority=92, title="小红书招聘"),
    RecruitingSource("哔哩哔哩", ("哔哩哔哩", "bilibili", "B站"), "https://jobs.bilibili.com/", "official_company", "互联网", "民企", priority=91, title="哔哩哔哩招聘"),
    RecruitingSource("360集团", ("360集团", "奇虎360"), "https://360campus.zhiye.com/", "official_company", "互联网安全", "民企", priority=89, title="360校园招聘"),
    RecruitingSource("vivo", ("vivo", "维沃"), "https://hr.vivo.com/", "official_company", "消费电子", "民企", priority=90, title="vivo招聘"),
    RecruitingSource("OPPO", ("oppo", "欧珀"), "https://careers.oppo.com/", "official_company", "消费电子", "民企", priority=90, title="OPPO招聘"),
    RecruitingSource("米哈游", ("米哈游", "mihoyo"), "https://jobs.mihoyo.com/", "official_company", "游戏", "民企", priority=90, title="米哈游招聘"),
    RecruitingSource("叠纸游戏", ("叠纸游戏", "叠纸", "papegames"), "https://career.papegames.com/", "official_company", "游戏", "民企", priority=87, title="叠纸游戏招聘"),
    RecruitingSource("联想", ("联想", "lenovo"), "https://talent.lenovo.com.cn/", "official_company", "消费电子", "民企", priority=89, title="联想招聘"),
    RecruitingSource("蔚来", ("蔚来", "nio"), "https://nio.jobs.feishu.cn/", "official_company", "汽车", "民企", priority=88, title="蔚来招聘"),
    RecruitingSource("理想汽车", ("理想汽车", "理想"), "https://www.lixiang.com/careers", "official_company", "汽车", "民企", priority=88, title="理想汽车招聘"),
    RecruitingSource("小鹏汽车", ("小鹏汽车", "小鹏"), "https://xiaopeng.jobs.feishu.cn/", "official_company", "汽车", "民企", priority=88, title="小鹏汽车招聘"),
    RecruitingSource("吉利汽车", ("吉利汽车", "吉利"), "https://campus.geely.com/", "official_company", "汽车", "民企", priority=88, title="吉利校园招聘"),
    RecruitingSource("比亚迪", ("比亚迪", "byd"), "https://job.byd.com/", "official_company", "汽车", "民企", priority=90, title="比亚迪招聘"),
    RecruitingSource("宁德时代", ("宁德时代", "catl"), "https://career.catl.com/", "official_company", "新能源", "民企", priority=91, title="宁德时代招聘"),
    RecruitingSource("大疆", ("大疆", "dji"), "https://we.dji.com/zh-CN/campus", "official_company", "智能硬件", "民企", priority=90, title="大疆校园招聘"),
    RecruitingSource("长鑫存储", ("长鑫存储", "cxmt"), "https://career.cxmt.com/", "official_company", "半导体", "民企", priority=90, title="长鑫存储招聘"),
    RecruitingSource("中汽中心", ("中汽中心", "中国汽车技术研究中心"), "https://catarc.zhiye.com/", "official_company", "汽车", "央企", priority=88, title="中汽中心招聘"),
    RecruitingSource("华泰证券", ("华泰证券",), "https://job.htsc.com.cn/", "official_company", "证券金融", "国企", priority=86, title="华泰证券招聘"),
    RecruitingSource("招商银行", ("招商银行", "招行", "cmb"), "https://career.cmbchina.com/", "official_company", "银行金融", "股份制企业", priority=89, title="招商银行招聘"),
    RecruitingSource("平安集团", ("平安集团", "中国平安", "平安银行"), "https://campus.pingan.com/", "official_company", "金融保险", "民企", priority=87, title="平安校园招聘"),
    RecruitingSource("微软", ("微软", "microsoft"), "https://jobs.careers.microsoft.com/global/en/search?lc=China", "official_company", "科技", "外企", priority=86, title="微软中国招聘"),
    RecruitingSource("苹果", ("苹果", "apple"), "https://jobs.apple.com/zh-cn/search?location=china-CHNC", "official_company", "科技", "外企", priority=86, title="苹果中国招聘"),
    RecruitingSource("英特尔", ("英特尔", "intel"), "https://jobs.intel.com/zh-hans/", "official_company", "半导体", "外企", priority=86, title="英特尔招聘"),
    RecruitingSource("IBM", ("ibm", "国际商业机器"), "https://www.ibm.com/careers/search", "official_company", "科技", "外企", priority=84, title="IBM招聘"),
    RecruitingSource("高通", ("高通", "qualcomm"), "https://careers.qualcomm.com/careers", "official_company", "半导体", "外企", priority=84, title="高通招聘"),
    RecruitingSource("戴尔", ("戴尔", "dell"), "https://jobs.dell.com/zh-cn/", "official_company", "科技", "外企", priority=83, title="戴尔招聘"),
    RecruitingSource("国聘", (), "https://www.iguopin.com/", "job_board", "综合", "平台", trust_level="A", priority=92, title="国聘招聘平台"),
    RecruitingSource("牛客校招", (), "https://www.nowcoder.com/jobs/school", "job_board", "综合", "平台", trust_level="B", priority=86, title="牛客校招"),
    RecruitingSource("前程无忧校园招聘", (), "https://campus.51job.com/", "job_board", "综合", "平台", trust_level="B", priority=84, title="前程无忧校园招聘"),
    RecruitingSource("国务院国资委", (), "https://www.sasac.gov.cn/n2588035/n2588325/", "government", "央企综合", "政府", trust_level="S", priority=96, title="国务院国资委招聘信息"),
    RecruitingSource("上海市国资委", (), "https://www.gzw.sh.gov.cn/", "government", "国企综合", "政府", trust_level="S", priority=90, title="上海国资国企招聘"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _compact(value: str) -> str:
    return "".join((value or "").lower().split())


def source_for_text(text: str) -> RecruitingSource | None:
    compact = _compact(text)
    matches: list[tuple[int, int, RecruitingSource]] = []
    for source in SOURCES:
        for alias in source.aliases:
            compact_alias = _compact(alias)
            if compact_alias and compact_alias in compact:
                matches.append((len(compact_alias), source.priority, source))
    return max(matches, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]


def source_for_url(url: str) -> RecruitingSource | None:
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    if not host:
        return None
    matches = [
        source for source in SOURCES
        if host == urlparse(source.url).netloc.lower().removeprefix("www.")
    ]
    return max(matches, default=None, key=lambda source: source.priority)


def sources_for_keyword(keyword: str, limit: int = 20) -> list[RecruitingSource]:
    compact = _compact(keyword)
    matches = []
    seen: set[str] = set()
    for source in sorted(SOURCES, key=lambda item: item.priority, reverse=True):
        if not source.aliases:
            continue
        if not any(_compact(alias) in compact for alias in source.aliases):
            continue
        if source.url in seen:
            continue
        seen.add(source.url)
        matches.append(source)
        if len(matches) >= limit:
            break
    return matches


def ensure_source_registry(conn: Any) -> None:
    ts = utc_now()
    conn.executemany(
        """
        INSERT INTO sources(name, source_type, url, trust_level, priority, check_interval_minutes,
            parser_type, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            name=excluded.name,
            source_type=excluded.source_type,
            trust_level=excluded.trust_level,
            priority=excluded.priority,
            check_interval_minutes=excluded.check_interval_minutes,
            parser_type=excluded.parser_type,
            updated_at=excluded.updated_at
        """,
        [
            (
                source.name,
                source.source_type,
                source.url,
                source.trust_level,
                source.priority,
                360 if source.source_type == "official_company" else 180,
                source.parser_type,
                ts,
                ts,
            )
            for source in SOURCES
        ],
    )


def registry_items() -> list[dict[str, Any]]:
    return [asdict(source) for source in sorted(SOURCES, key=lambda item: item.priority, reverse=True)]
