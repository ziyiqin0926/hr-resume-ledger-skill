import base64
import csv
import json
import os
import re
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import zipfile
import xml.sax.saxutils as xml_utils
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    RUNTIME_DIR = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
    RUNTIME_DIR = ROOT

DATA_DIR = RUNTIME_DIR / "data"
STATIC_DIR = ROOT / "static"
DB_PATH = DATA_DIR / "hr_resume_ledger.sqlite3"
PDF_DIR = DATA_DIR / "resume_pdfs"
APP_HOST = os.environ.get("HR_LEDGER_HOST", os.environ.get("APP_HOST", "127.0.0.1"))
APP_PORT = int(os.environ.get("HR_LEDGER_PORT", os.environ.get("APP_PORT", "8765")))
CDP_PORT = int(os.environ.get("HR_LEDGER_CDP_PORT", "9222"))
DEFAULT_COLLECT_LIMIT = 500
PLATFORMS = {
    "zhaopin": {
        "id": "zhaopin", "name": "智联招聘", "home": "https://rd5.zhaopin.com/",
        "url_keywords": ["zhaopin.com", "rd6.zhaopin.com/app/recommend"],
        "candidate_keywords": ["resume", "candidate", "talent", "rd5", "rd6", "zhaopin", "recommend"],
    },
    "boss": {
        "id": "boss", "name": "BOSS直聘", "home": "https://www.zhipin.com/",
        "url_keywords": ["zhipin.com", "bosszhipin.com"],
        "candidate_keywords": ["geek", "resume", "candidate", "detail", "zhipin"],
    },
    "liepin": {
        "id": "liepin", "name": "猎聘", "home": "https://www.liepin.com/",
        "url_keywords": ["liepin.com", "lpt.liepin.com"],
        "candidate_keywords": ["resume", "candidate", "talent", "detail", "liepin"],
    },
    "generic": {
        "id": "generic", "name": "通用页面", "home": "about:blank",
        "url_keywords": [],
        "candidate_keywords": ["resume", "candidate", "talent", "detail", "profile", "简历", "候选人"],
    },
}
EXPORT_FIELDS = [
    "姓名", "电话", "工作经历匹配度", "匹配说明", "相关经历",
    "年龄", "性别", "学历", "求职状态", "微信", "邮箱", "个人基本资料",
]
XLSX_FIELDS = ["跟进状态", "优先级", "最近跟进时间", "跟进人", "备注"] + EXPORT_FIELDS

PROGRESS = {}


def get_platform(platform="zhaopin"):
    return PLATFORMS.get(platform or "zhaopin") or PLATFORMS["generic"]


def platform_matches_url(platform, url):
    p = get_platform(platform)
    if p["id"] == "generic":
        return True
    s = (url or "").lower()
    return any(k.lower() in s for k in p["url_keywords"])


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                education TEXT NOT NULL DEFAULT '',
                age TEXT NOT NULL DEFAULT '',
                age_years TEXT NOT NULL DEFAULT '',
                gender TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                wechat TEXT NOT NULL DEFAULT '',
                basic_info TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                job_desc TEXT NOT NULL DEFAULT '',
                matched_experience TEXT NOT NULL DEFAULT '',
                resume TEXT NOT NULL DEFAULT '',
                work_trace TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                resume_key TEXT NOT NULL DEFAULT '',
                local_pdf_path TEXT NOT NULL DEFAULT '',
                raw_text TEXT NOT NULL DEFAULT ''
            )
            """
        )
        cols = {r[1] for r in con.execute("PRAGMA table_info(candidates)")}
        for col in ["education", "age", "age_years", "gender", "email", "wechat", "basic_info", "status", "job_desc", "matched_experience", "resume", "work_trace", "source_url", "resume_key", "local_pdf_path", "raw_text"]:
            if col not in cols:
                con.execute(f"ALTER TABLE candidates ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")


def rows_to_dicts(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def clean_lines(text):
    return [x.strip() for x in re.split(r"[\r\n]+", text or "") if x.strip()]


def split_keywords(text):
    return [x.strip() for x in re.split(r"[,，、;；\s]+", text or "") if x.strip()]


def set_progress(run_id="default", **data):
    state = PROGRESS.setdefault(run_id or "default", {"total": 0, "current": 0, "message": "", "items": [], "done": False})
    state.update(data)
    return state


def get_progress(run_id="default"):
    return PROGRESS.get(run_id or "default", {"total": 0, "current": 0, "message": "", "items": [], "done": False})


def extract_contacts(text):
    compact = "\n".join(clean_lines(text))
    phones = re.findall(r"(?<!\d)(?:\+?86[-\s]?)?(1[3-9]\d{9})(?!\d)", compact)
    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", compact)
    wm = re.search(r"(?:微信|wechat|WeChat|VX|vx)[:：\s]*([A-Za-z][-_A-Za-z0-9]{5,19})", compact)
    return {
        "phone": phones[0] if phones else "",
        "phones": "、".join(dict.fromkeys(phones)),
        "email": emails[0] if emails else "",
        "wechat": wm.group(1) if wm else "",
    }


def extract_profile_info(text):
    lines = clean_lines(text)
    compact = "\n".join(lines)
    age = ""
    m = re.search(r"(?<!\d)(1[6-9]|[2-5]\d|60)\s*岁", compact)
    if m:
        age = m.group(1)
    years = []
    for pat in [r"\d+\s*年(?:工作)?经验", r"\d+\s*年", r"应届生", r"\d{2,4}\s*届"]:
        years += re.findall(pat, compact)
    gender = ""
    if re.search(r"(^|[\s，,])男([\s，,]|$)", compact):
        gender = "男"
    elif re.search(r"(^|[\s，,])女([\s，,]|$)", compact):
        gender = "女"
    status = next((x for x in lines if "找工作" in x or "看看机会" in x or "在职" in x or "离职" in x), "")
    basic_lines = [x for x in lines if any(k in x for k in ["岁", "男", "女", "经验", "现居", "居住", "所在地", "城市", "期望", "邮箱", "微信", "手机", "电话"])][:12]
    return {
        "age": age,
        "age_years": " / ".join(dict.fromkeys(years[:4])),
        "gender": gender,
        "status": status,
        "basic_info": "\n".join(basic_lines),
    }


EDU_LEVELS = ["博士", "硕士", "研究生", "本科", "大专", "专科", "高中", "中专"]
TERM_SYNONYMS = {
    "陪诊师": ["陪诊", "导医", "导诊", "分诊", "医院导医", "接待咨询", "护士", "医生助理", "辅诊"],
    "陪诊": ["陪诊师", "导医", "导诊", "分诊", "医院导医", "接待咨询"],
    "导医": ["陪诊", "陪诊师", "导诊", "分诊", "医院导医", "接待咨询"],
}


def expand_terms(terms):
    out = []
    for t in terms:
        out.append(t)
        out.extend(TERM_SYNONYMS.get(t, []))
    return list(dict.fromkeys([x for x in out if x]))


def extract_education(text):
    return next((e for e in EDU_LEVELS if e in (text or "")), "")


def extract_experience_segments(text):
    lines = clean_lines(text)
    segs = []
    for line in lines:
        if re.search(r"(20\d{2}|19\d{2}|至今|工作经历|项目经历|教育经历|证书|资格|专业|公司|负责|岗位|职位|医院|护士|护理)", line):
            segs.append(line)
    return segs or lines[:20]


def extract_expected_role(lines):
    skip = {"期望：", "期望", "期望职位：", "期望职位", "最近关注：", "最近关注", "打电话", "打招呼"}
    role_words = ["导医", "护士", "护理", "销售", "经理", "主管", "专员", "顾问", "运营", "客服", "行政", "招聘", "后端", "前端", "会计", "出纳", "教师", "物流", "仓储", "医生", "临床"]
    for i, line in enumerate(lines):
        if line in ("期望：", "期望", "期望职位：", "期望职位"):
            for cand in lines[i + 1:i + 5]:
                s = cand.strip()
                if not s or s in skip:
                    continue
                if re.search(r"^\d+岁$|^\d+年|应届生|本科|大专|硕士|博士|千|万|南京|上海|北京|广州|深圳|合肥|南通", s):
                    continue
                return s
    for line in lines:
        s = line.strip()
        if s in skip:
            continue
        if any(w in s for w in role_words) and not re.search(r"^\d+岁$|^\d+年|应届生|本科|大专|硕士|博士|资格证|执业证|公立医院|内科|康复科", s):
            return s
    return ""


def matched_experience(text, job_keywords):
    terms = split_keywords(job_keywords)
    segs = extract_experience_segments(text)
    all_lines = clean_lines(text)
    if not terms:
        return "\n".join(segs[:5])
    hits = []
    for seg in segs + [x for x in all_lines if x not in segs]:
        if seg in ("打电话", "打招呼") or "分钟前" in seg or "小时前" in seg:
            continue
        if any(k in seg for k in ["求职期望", "期望职位", "期望：", "求职意向"]):
            continue
        if any(semantic_term_hit(t, seg) for t in terms):
            hits.append(seg)
    return "\n".join(hits[:8])


def matches_requirements(payload, job_keywords):
    text = payload.get("text", "") if isinstance(payload, dict) else str(payload or "")
    terms = split_keywords(job_keywords)
    if not terms:
        return True
    lower = text.lower()
    return sum(1 for t in terms if t.lower() in lower) >= max(1, min(2, len(terms)))


def build_trace(candidate, job_keywords, source_page=""):
    matched = candidate.get("matched_experience", "")
    return {
        "requirements": job_keywords or "",
        "source_page": source_page or "",
        "source_url": candidate.get("source_url", ""),
        "matched": matched,
        "decision": "保存：有电话且命中筛选要求" if candidate.get("phone") and (not job_keywords or matched) else "跳过：无电话或未命中",
    }


def guess_name(lines, title=""):
    job_words = ["经理", "主管", "专员", "顾问", "导医", "护士", "销售", "运营", "客服", "行政", "招聘", "岗位", "职位", "工程师", "会计", "出纳", "负责", "团队", "管理", "经验"]
    def is_bad_name(s):
        return any(w in s for w in job_words)
    joined = "\n".join(lines[:80])
    m = re.search(r"(?:姓名|候选人)[:：\s]*([\u4e00-\u9fa5]{2,4})", joined)
    if m and not is_bad_name(m.group(1)):
        return m.group(1)
    for line in lines[:20]:
        m = re.search(r"^\s*([\u4e00-\u9fa5]{2,4})\s*(?:电话|手机|1[3-9]\d{9})", line)
        if m and not is_bad_name(m.group(1)):
            return m.group(1)
    for i, line in enumerate(lines[:120]):
        s = line.strip()
        if re.match(r"^[\u4e00-\u9fa5]{1,4}(先生|女士)$", s) and any("岁" in x for x in lines[i:i + 6]):
            return s
    bad = ["智联", "招聘", "推荐", "首页", "简历", "电话", "手机", "邮箱", "求职", "工作", "经验", "本科", "硕士", "搜索", "聊天", "互动", "职位", "道具", "企业管理", "更多", "个人中心", "猎头服务", "资质公示", "法律协议", "手机版", "帮助中心"] + job_words
    sources = re.split(r"[-_|｜—\s]+", title or "") + lines[:40]
    for item in sources:
        s = re.sub(r"[^\u4e00-\u9fa5A-Za-z]", "", item).strip()
        if 2 <= len(s) <= 6 and re.search(r"[\u4e00-\u9fa5]", s) and not any(b in s for b in bad):
            return s
    return ""


def extract_candidate(payload, job_keywords=""):
    text = (payload.get("text") or "").strip()
    title = payload.get("title", "") or ""
    url = payload.get("url", "") or ""
    lines = clean_lines(text)
    compact = "\n".join(lines)
    contacts = extract_contacts(compact)
    profile = extract_profile_info(compact)
    phone = contacts["phone"]
    terms = split_keywords(job_keywords)
    lower_text = compact.lower()
    matched = [k for k in terms if k.lower() in lower_text]
    hit_exp = matched_experience(text, job_keywords)
    suitable = bool(phone) and (True if not terms else bool(hit_exp))
    education = extract_education(compact)
    return {
        "name": guess_name(lines, title),
        "phone": phone,
        "email": contacts["email"],
        "wechat": contacts["wechat"],
        "age": profile["age"],
        "age_years": profile["age_years"],
        "gender": profile["gender"],
        "status": profile["status"],
        "basic_info": profile["basic_info"],
        "education": education,
        "matched_experience": hit_exp,
        "resume": text[:60000],
        "raw_text": text[:60000],
        "source_url": url,
        "resume_key": extract_resume_key(url),
        "source_title": title,
        "matched": "、".join(matched),
        "suitable": suitable,
        "work_trace": json.dumps(build_trace({
            "phone": phone, "source_url": url, "matched_experience": hit_exp
        }, job_keywords, url), ensure_ascii=False),
    }


def extract_candidates_from_text(text, job_keywords=""):
    text = (text or "").strip()
    if not text:
        return []
    blocks = [b.strip() for b in re.split(r"\n\s*(?:-{2,}|={2,}|候选人[:：]?)\s*\n?", text) if b.strip()]
    if len(blocks) <= 1:
        hits = list(re.finditer(r"(?<!\d)(?:\+?86[-\s]?)?(1[3-9]\d{9})(?!\d)", text))
        if len(hits) > 1:
            blocks = []
            for i, m in enumerate(hits):
                start = hits[i - 1].end() if i else 0
                end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
                blocks.append(text[start:end].strip())
    rows, seen = [], set()
    for block in blocks:
        c = extract_candidate({"title": "", "url": "", "text": block}, job_keywords)
        key = c.get("phone") or c.get("name")
        if c.get("phone") and key not in seen:
            seen.add(key)
            rows.append(c)
    return rows


def extract_recommendation_cards(text, job_keywords=""):
    lines = clean_lines(text)
    name_re = re.compile(r"^[\u4e00-\u9fa5]{1,4}(?:先生|女士)$")
    starts = [i for i, line in enumerate(lines) if name_re.match(line)]
    rows = []
    seen_names = {}
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        block_lines = lines[start:end]
        block = "\n".join(block_lines)
        name = block_lines[0]
        occurrence = seen_names.get(name, 0)
        seen_names[name] = occurrence + 1
        edu = extract_education(block)
        contacts = extract_contacts(block)
        profile = extract_profile_info(block)
        phone = contacts["phone"]
        age_years = profile["age_years"] or " / ".join([x for x in block_lines if re.search(r"^\d+岁$|^\d+年$|应届生|毕业", x)][:3])
        status = profile["status"]
        job_desc = extract_expected_role(block_lines)
        hit = matched_experience(block, job_keywords)
        if not hit and matches_requirements({"text": block}, job_keywords):
            hit = "\n".join([x for x in block_lines if x not in ("打电话", "打招呼")][:12])
        c = {
            "name": name,
            "card_index": idx,
            "name_occurrence": occurrence,
            "phone": phone,
            "email": contacts["email"],
            "wechat": contacts["wechat"],
            "education": edu,
            "age": profile["age"],
            "age_years": age_years,
            "gender": profile["gender"],
            "status": status,
            "basic_info": profile["basic_info"],
            "job_desc": job_desc,
            "matched_experience": hit,
            "resume": block[:60000],
            "raw_text": block[:60000],
            "source_url": "",
            "source_title": "推荐页列表",
            "matched": "",
            "suitable": bool(not job_keywords or hit),
        }
        c["work_trace"] = json.dumps(build_trace(c, job_keywords, ""), ensure_ascii=False)
        rows.append(c)
    return rows


def candidate_match_score(candidate, job_keywords):
    terms = split_keywords(job_keywords)
    text = "\n".join([
        candidate.get("name", ""),
        candidate.get("education", ""),
        candidate.get("matched_experience", ""),
        candidate.get("resume", ""),
    ]).lower()
    if not terms:
        return {"score": 100, "matched": True, "hit_terms": [], "reason": "未填写筛选要求，默认纳入"}
    hit_terms = [t for t in terms if t.lower() in text]
    score = round(100 * len(hit_terms) / len(terms))
    matched = score >= 50
    return {
        "score": score,
        "matched": matched,
        "hit_terms": hit_terms,
        "reason": f"命中 {len(hit_terms)}/{len(terms)}：{'、'.join(hit_terms) if hit_terms else '无'}",
    }


def semantic_match_score(candidate, job_keywords):
    if not job_keywords:
        return {"score": 100, "matched": True, "hit_terms": [], "reason": "未填写筛选要求，默认纳入"}
    result = evaluate_candidate(candidate, parse_requirements(job_keywords))
    return {
        "score": result["score"],
        "matched": result["matched"],
        "hit_terms": result.get("hit_terms", []),
        "reason": "；".join(result.get("reasons", [])),
    }


def parse_requirements(text):
    raw = text or ""
    hard_part = raw
    bonus_part = ""
    m = re.search(r"硬性[:：](.*?)(?:加分[:：](.*))?$", raw)
    if m:
        hard_part = m.group(1)
        bonus_part = m.group(2) or ""
    age_range = None
    am = re.search(r"(\d{2})\s*[-~到至]\s*(\d{2})", hard_part)
    if am:
        age_range = (int(am.group(1)), int(am.group(2)))
    contact_required = bool(re.search(r"(必须|必需|要求)[^；;。,.，]*?(联系方式|电话|手机)", raw))
    strict_education = bool(re.search(r"(必须|必需|要求)[^；;。,.，]*?(本科|大专|学历)", raw))
    strict_age = bool(re.search(r"(必须|必需|要求)[^；;。,.，]*?(年龄|\d{2}\s*[-~到至]\s*\d{2})", raw))
    edu_required = ""
    if "本科" in hard_part:
        edu_required = "本科"
    elif "大专" in hard_part:
        edu_required = "大专"
    cleaned_hard = re.sub(r"(必须|必需|要求)?\s*年龄[:：]?\s*\d{2}\s*[-~到至]\s*\d{2}|\d{2}\s*[-~到至]\s*\d{2}|硬性|岗位|年龄|必须|必需|要求|及以上|有联系方式|联系方式", " ", hard_part)
    hard_terms = [t for t in split_keywords(cleaned_hard) if t]
    bonus_terms = split_keywords(bonus_part)
    return {"raw": raw, "hard_terms": hard_terms, "bonus_terms": bonus_terms, "age_range": age_range, "contact_required": contact_required, "education": edu_required, "strict_education": strict_education, "strict_age": strict_age}


def education_rank(value):
    s = value or ""
    if "博士" in s:
        return 5
    if "硕士" in s or "研究生" in s:
        return 4
    if "本科" in s:
        return 3
    if "大专" in s or "专科" in s:
        return 2
    if "高中" in s or "中专" in s:
        return 1
    return 0


SEMANTIC_ALIASES = {
    "医疗": ["医疗", "医院", "门诊", "临床", "医生", "护士", "护理", "中医", "中药", "中医药", "西医", "药房", "药店", "导医", "分诊", "接诊", "患者", "病历", "康复", "检验", "影像"],
    "医疗相关经历": ["医疗", "医院", "门诊", "临床", "医生", "护士", "护理", "中医", "中药", "中医药", "西医", "药房", "药店", "导医", "导诊", "分诊", "接诊", "患者", "病历", "康复", "检验", "影像"],
    "中医药": ["中医", "中药", "中医药", "中医馆", "调理", "针灸", "推拿", "药材"],
    "西医临床": ["西医", "临床", "门诊", "接诊", "病历", "医生助理", "临床助理"],
    "导医": ["导医", "分诊", "导诊", "预检分诊", "患者接待", "客户接待", "前台", "医院", "门诊", "咨询"],
    "护士": ["护士", "护理", "护师", "护士资格证", "护理资格证"],
    "护士资格证": ["护士资格证", "护士执业证", "护士执业证书", "护理资格证", "护理证书"],
    "护理专业": ["护理专业", "护理", "护理学"],
    "护理专业专科": ["护理专业", "护理", "护理学", "专科", "大专"],
    "专科": ["专科", "大专"],
    "客服": ["客服", "客户服务", "售后", "接待", "咨询", "工单", "客诉"],
    "行政": ["行政", "文员", "内勤", "办公室", "资料整理"],
    "销售": ["销售", "客户开发", "获客", "BD", "商务拓展", "陌拜", "转化", "签单", "回款", "渠道"],
    "销售顾问": ["销售", "客户开发", "获客", "BD", "商务拓展", "陌拜", "转化", "签单", "回款", "顾问式销售"],
    "销售经理": ["销售经理", "销售主管", "销售负责人", "销售管理", "带团队", "销售团队", "团队管理", "业绩目标", "销售计划", "渠道拓展", "大客户", "KA", "签单回款"],
    "销售主管": ["销售主管", "销售经理", "销售负责人", "带团队", "销售团队", "团队管理", "业绩目标", "渠道客户开发"],
    "渠道经理": ["渠道经理", "渠道拓展", "渠道开发", "代理商", "经销商", "渠道客户开发", "商务拓展"],
    "大客户经理": ["大客户经理", "KA", "大客户", "重点客户", "客户关系", "商务谈判", "签单回款"],
    "团队管理": ["团队管理", "带团队", "带领", "管理团队", "销售团队", "人员培养", "目标拆解"],
    "渠道拓展": ["渠道拓展", "渠道开发", "渠道客户开发", "商务拓展", "代理商", "经销商"],
    "客户开发": ["客户开发", "获客", "BD", "商务拓展", "陌拜", "转化", "签单", "渠道拓展"],
    "市场": ["市场", "营销", "推广", "投放", "活动策划", "品牌", "新媒体"],
    "运营": ["运营", "用户运营", "内容运营", "社群", "活动运营", "数据分析", "转化"],
    "新媒体运营": ["新媒体运营", "公众号", "推文", "短视频", "内容发布", "社群增长", "活动复盘", "数据分析", "小红书", "抖音", "内容运营", "粉丝增长"],
    "内容运营": ["内容运营", "内容策划", "公众号", "推文", "短视频", "选题", "发布", "数据复盘"],
    "短视频运营": ["短视频运营", "抖音", "快手", "视频发布", "脚本", "拍摄", "剪辑", "数据复盘"],
    "电商运营": ["电商运营", "淘宝", "天猫", "京东", "拼多多", "店铺运营", "商品上架", "活动报名", "转化率"],
    "人事": ["人事", "HR", "招聘", "员工关系", "薪酬", "绩效", "社保"],
    "招聘专员": ["招聘专员", "招聘", "简历筛选", "电话邀约", "面试安排", "offer沟通", "入职跟进", "招聘渠道"],
    "HRBP": ["HRBP", "人力资源", "业务支持", "组织发展", "员工关系", "绩效", "招聘"],
    "财务": ["财务", "会计", "出纳", "做账", "报税", "发票", "应收", "应付"],
    "物流": ["物流", "仓储", "仓库", "配送", "发货", "供应链", "库存"],
    "教育": ["教育", "教师", "老师", "培训", "教务", "课程", "班主任"],
    "Python后端": ["Python", "Django", "Flask", "FastAPI", "后端", "REST", "接口", "服务端"],
    "后端": ["后端", "服务端", "接口", "API", "REST", "数据库"],
    "API": ["API", "接口", "REST", "HTTP", "服务"],
    "MySQL": ["MySQL", "SQL", "数据库", "表结构", "SQL优化"],
}


def semantic_term_hit(term, text):
    aliases = SEMANTIC_ALIASES.get(term, [term])
    return any(a and a.lower() in text.lower() for a in aliases)


def evaluate_candidate(candidate, req):
    text = "\n".join([candidate.get("resume", ""), candidate.get("matched_experience", ""), candidate.get("basic_info", ""), candidate.get("education", "")])
    reasons, hard_fail = [], []
    if candidate.get("detail_success") is False:
        hard_fail.append("详情页未验证，不能作为最终命中")
    if req.get("contact_required") and not (candidate.get("phone") or candidate.get("email") or candidate.get("wechat")):
        hard_fail.append("缺少联系方式")
    if req.get("strict_education") and req.get("education") and education_rank(candidate.get("education") or text) < education_rank(req["education"]):
        hard_fail.append("学历不满足")
    if req.get("strict_age") and req.get("age_range"):
        if not candidate.get("age"):
            hard_fail.append("年龄未识别")
        else:
            age = int(candidate["age"])
            lo, hi = req["age_range"]
            if age < lo or age > hi:
                hard_fail.append("年龄不满足")
    hit_terms = [t for t in req.get("hard_terms", []) if semantic_term_hit(t, text)]
    required_terms = [t for t in req.get("hard_terms", []) if not re.fullmatch(r"\d+", t) and t not in ("本科", "大专")]
    if required_terms and len(hit_terms) < max(1, round(len(required_terms) * 0.6)):
        hard_fail.append("岗位/经历语义不匹配")
    bonus_hits = [t for t in req.get("bonus_terms", []) if semantic_term_hit(t, text)]
    hard_pass = not hard_fail
    score = 0 if not hard_pass else min(100, round(
        80 * (len(hit_terms) / max(1, len(required_terms))) +
        20 * (len(bonus_hits) / max(1, len(req.get("bonus_terms", []))))
    ))
    reasons += [f"命中经历：{'、'.join(hit_terms) if hit_terms else '无'}"]
    if bonus_hits:
        reasons.append(f"加分：{'、'.join(bonus_hits)}")
    reasons += hard_fail
    if hard_pass and score < 60:
        reasons.append("岗位/经历语义不匹配")
    return {"matched": hard_pass and score >= 60, "hard_pass": hard_pass, "score": score, "reasons": reasons, "hit_terms": hit_terms, "bonus_hits": bonus_hits}


def build_calibrated_match_report(candidates, req):
    items = []
    for c in candidates:
        row = dict(c)
        row.update(evaluate_candidate(c, req))
        items.append(row)
    total = len(items)
    matched = sum(1 for x in items if x["matched"])
    return {"total": total, "matched": matched, "percent": round(100 * matched / total) if total else 0, "items": items}


def build_match_report(candidates, job_keywords):
    items = []
    for c in candidates:
        m = semantic_match_score(c, job_keywords)
        row = dict(c)
        row.update(m)
        items.append(row)
    total = len(items)
    matched = sum(1 for x in items if x["matched"])
    percent = round(100 * matched / total) if total else 0
    return {"total": total, "matched": matched, "percent": percent, "items": items}


def find_browser():
    for exe in [
        os.environ.get("CHROME"), os.environ.get("EDGE"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]:
        if exe and Path(exe).exists():
            return exe
    return None


def launch_browser(platform="zhaopin"):
    exe = find_browser()
    if not exe:
        raise RuntimeError("未找到 Chrome 或 Edge")
    profile = DATA_DIR / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([
        exe,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--new-window",
        get_platform(platform)["home"],
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "browser": exe, "port": CDP_PORT, "platform": get_platform(platform)["id"]}


def cdp_tabs():
    with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=2) as resp:
        tabs = json.loads(resp.read().decode("utf-8", "replace"))
    return [{"id": t.get("id"), "title": t.get("title", ""), "url": t.get("url", ""), "ws": t.get("webSocketDebuggerUrl", "")}
            for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]


def find_recommend_tab(platform="zhaopin"):
    tabs = cdp_tabs()
    for t in tabs:
        if platform_matches_url(platform, t.get("url") or ""):
            return t
    return None


class CdpWebSocket:
    def __init__(self, ws_url):
        parsed = urllib.parse.urlparse(ws_url)
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self.path = parsed.path + (("?" + parsed.query) if parsed.query else "")
        self.sock = socket.create_connection((self.host, self.port), timeout=8)
        self.next_id = 1
        self._handshake()

    def _handshake(self):
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {self.path} HTTP/1.1\r\nHost: {self.host}:{self.port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        if b" 101 " not in self.sock.recv(4096):
            raise RuntimeError("CDP WebSocket 握手失败")

    def _send_text(self, text):
        data = text.encode("utf-8")
        header = bytearray([0x81])
        if len(data) < 126:
            header.append(0x80 | len(data))
        elif len(data) < 65536:
            header.append(0x80 | 126); header.extend(struct.pack("!H", len(data)))
        else:
            header.append(0x80 | 127); header.extend(struct.pack("!Q", len(data)))
        mask = os.urandom(4)
        header.extend(mask)
        self.sock.sendall(header + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv_exact(self, n):
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise RuntimeError("CDP 连接已关闭")
            data += chunk
        return data

    def _recv_text(self):
        b1, b2 = self._recv_exact(2)
        opcode = b1 & 0x0F
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if (b2 & 0x80) else b""
        payload = self._recv_exact(length)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 8:
            raise RuntimeError("CDP WebSocket 已关闭")
        return payload.decode("utf-8", "replace") if opcode in (1, 2) else ""

    def call(self, method, params=None, timeout=10):
        msg_id = self.next_id
        self.next_id += 1
        self._send_text(json.dumps({"id": msg_id, "method": method, "params": params or {}}, ensure_ascii=False))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self._recv_text()
            if not raw:
                continue
            msg = json.loads(raw)
            if msg.get("id") == msg_id:
                return msg
        raise RuntimeError("等待 CDP 响应超时")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def eval_page(ws, expression, timeout=10):
    resp = ws.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}, timeout=timeout)
    result = resp.get("result", {}).get("result", {})
    return result.get("value", "")


def safe_filename(text):
    return re.sub(r"[^\w\u4e00-\u9fa5.-]+", "_", (text or "").strip()).strip("_")[:80] or "resume"


def extract_resume_key(url):
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url or "").query)
        rn = (q.get("resumeNumber") or [""])[0]
        jn = (q.get("jobNumber") or [""])[0]
        return f"{jn}|{rn}" if rn else ""
    except Exception:
        return ""


def zhaopin_export_current_pdf(ws, candidate=None):
    """Call Zhilian's own '存至本地' PDF flow for the currently opened resume."""
    script = r"""
(async () => {
  const perf = performance.getEntriesByType('resource').map(x => x.name).reverse();
  const api = perf.find(u => u.includes('/api/resume/createExportTask')) || perf.find(u => u.includes('/api/resume/')) || location.href;
  const u = new URL(api, location.href);
  const loc = new URL(location.href);
  const pageReq = u.searchParams.get('x-zp-page-request-id') || '';
  const clientId = u.searchParams.get('x-zp-client-id') || '';
  const jobNumber = loc.searchParams.get('jobNumber') || '';
  const resumeNumber = loc.searchParams.get('resumeNumber') || '';
  if (!jobNumber || !resumeNumber) return JSON.stringify({ok:false, error:'缺少 jobNumber/resumeNumber', url: location.href});
  const query = () => new URLSearchParams({'_': Date.now(), 'x-zp-page-request-id': pageReq, 'x-zp-client-id': clientId}).toString();
  const taskResp = await fetch('/api/resume/createExportTask?' + query(), {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({fileType:'PDF', exportItems:[{jobNumber, resumeNumber, resumeLanguage:'1'}], enterScene:'RECOMMEND_TAB'})
  });
  const task = await taskResp.json();
  const fileId = task.data || task.taskId;
  if (!fileId) return JSON.stringify({ok:false, error:'未返回 fileId', task});
  let file = null;
  for (let i = 0; i < 8; i++) {
    await new Promise(r => setTimeout(r, i ? 1200 : 1800));
    const fileResp = await fetch('/api/resume/saveLocal/getFile?' + query(), {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({fileId})
    });
    file = await fileResp.json();
    if (file && file.data && file.data.state === 'READY' && file.data.fileUrl) break;
  }
  return JSON.stringify({ok: !!(file && file.data && file.data.fileUrl), jobNumber, resumeNumber, fileId, file});
})()
"""
    raw = eval_page(ws, script, timeout=25)
    info = json.loads(raw or "{}")
    file_url = (((info.get("file") or {}).get("data") or {}).get("fileUrl") or "").strip()
    if not info.get("ok") or not file_url:
        return {"ok": False, "error": info.get("error") or "PDF 文件未就绪", "info": info}
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    name = safe_filename((candidate or {}).get("name") or info.get("resumeNumber") or "resume")
    filename = f"{name}_{info.get('resumeNumber','')}_{int(time.time())}.pdf"
    path = PDF_DIR / filename
    with urllib.request.urlopen(file_url, timeout=30) as resp:
        data = resp.read()
    if not data.startswith(b"%PDF"):
        return {"ok": False, "error": "下载结果不是 PDF", "bytes": len(data)}
    path.write_bytes(data)
    return {"ok": True, "path": str(path), "url": file_url, "resumeNumber": info.get("resumeNumber"), "jobNumber": info.get("jobNumber")}

PAGE_SCRIPT = r"""
(() => JSON.stringify({
  title: document.title || '',
  url: location.href || '',
  text: (document.body && document.body.innerText ? document.body.innerText : '').slice(0, 60000),
  links: Array.from(document.querySelectorAll('a[href]')).map(a => ({
    href: a.href,
    text: (a.innerText || a.textContent || '').trim().slice(0, 120)
  })).filter(x => x.href).slice(0, 1000)
}))()
"""


def read_current_page(ws):
    value = eval_page(ws, PAGE_SCRIPT)
    return json.loads(value or "{}")


def read_recommend_page_when_ready(ws, wait_seconds=8):
    deadline = time.time() + wait_seconds
    last_page = {}
    while time.time() < deadline:
        last_page = read_current_page(ws)
        cards = extract_recommendation_cards(last_page.get("text", ""), "")
        if len(cards) >= 3:
            return last_page, cards
        time.sleep(0.8)
    return last_page, extract_recommendation_cards(last_page.get("text", ""), "")


def wait_page_changed(ws, old_url="", old_text="", wait_seconds=6):
    deadline = time.time() + wait_seconds
    last_page = {}
    while time.time() < deadline:
        last_page = read_current_page(ws)
        new_url = last_page.get("url", "")
        new_text = last_page.get("text", "")
        if new_url != old_url or (new_text and new_text != old_text and len(new_text) > 500):
            return last_page
        time.sleep(0.6)
    return last_page


def capture_tab(ws_url, job_keywords=""):
    ws = CdpWebSocket(ws_url)
    try:
        page = read_current_page(ws)
    finally:
        ws.close()
    return {"page": page, "candidate": extract_candidate(page, job_keywords)}


def looks_candidate_link(link, platform="zhaopin"):
    s = ((link.get("href") or "") + " " + (link.get("text") or "")).lower()
    if any(x in s for x in ["logout", "login", "setting", "help", "javascript:"]):
        return False
    return any(x.lower() in s for x in get_platform(platform)["candidate_keywords"])


def name_variants(name):
    base = re.sub(r"(先生|女士)$", "", (name or "").strip())
    return [x for x in [name, base] if x]


def find_candidate_href(page, candidate, platform="zhaopin"):
    links = page.get("links", []) or []
    variants = name_variants(candidate.get("name", ""))
    for link in links:
        text = link.get("text", "") or ""
        href = link.get("href", "") or ""
        if any(v and v in text for v in variants) and looks_candidate_link(link, platform):
            return href
    return ""


def click_candidate_by_name(ws, name, occurrence=0):
    js_name = json.dumps(name or "", ensure_ascii=False)
    js_occurrence = int(occurrence or 0)
    expression = f"""
(() => {{
  const name = {js_name};
  const occurrence = {js_occurrence};
  const base = name.replace(/(先生|女士)$/,'');
  const keys = [name, base].filter(Boolean);
  const nodes = Array.from(document.querySelectorAll('a[href],button,[role=button],li,section,div'))
    .filter(el => {{
      const t = (el.innerText || el.textContent || '').trim();
      return t && t.length < 1600 && keys.some(k => t.includes(k));
    }})
    .sort((a,b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top || (a.innerText||'').length - (b.innerText||'').length);
  const uniq = [];
  for (const el of nodes) {{
    const r = el.getBoundingClientRect();
    if (r.width < 20 || r.height < 10) continue;
    if (uniq.some(x => Math.abs(x.getBoundingClientRect().top - r.top) < 6)) continue;
    uniq.push(el);
  }}
  const picked = uniq[Math.min(occurrence, Math.max(0, uniq.length - 1))] || uniq[0];
  if (picked) {{
    const el = picked;
    const target = el.closest('a[href],button,[role=button]') || el.querySelector('a[href],button,[role=button]') || el;
    target.scrollIntoView({{block:'center'}});
    target.click();
    return JSON.stringify({{ok:true, occurrence, candidates: uniq.length, text:(target.innerText||target.textContent||'').trim().slice(0,120)}});
  }}
  return JSON.stringify({{ok:false}});
}})()
"""
    try:
        return json.loads(eval_page(ws, expression) or "{}")
    except Exception as e:
        return {"ok": False, "error": str(e)}


def click_candidate_card(ws, candidate):
    payload = json.dumps({
        "name": candidate.get("name", ""),
        "age": candidate.get("age", ""),
        "education": candidate.get("education", ""),
        "status": candidate.get("status", ""),
        "job_desc": candidate.get("job_desc", ""),
        "matched": clean_lines(candidate.get("matched_experience", ""))[:3],
    }, ensure_ascii=False)
    expression = f"""
(() => {{
  const c = {payload};
  const must = [c.name].filter(Boolean);
  const keys = [c.age && c.age + '岁', c.education, c.status, c.job_desc, ...(c.matched || [])].filter(Boolean);
  const nodes = Array.from(document.querySelectorAll('a[href],button,[role=button],li,section,div'))
    .map(el => {{
      const t = (el.innerText || el.textContent || '').trim();
      const r = el.getBoundingClientRect();
      const score = (must.every(k => t.includes(k)) ? 3 : -99) + keys.reduce((n,k) => n + (t.includes(k) ? 1 : 0), 0);
      return {{el,t,r,score}};
    }})
    .filter(x => x.score >= 5 && x.t.length < 1800 && x.r.width > 80 && x.r.height > 40)
    .sort((a,b) => b.score - a.score || a.t.length - b.t.length || a.r.top - b.r.top);
  const picked = nodes[0];
  if (!picked) return JSON.stringify({{ok:false, reason:'未找到字段匹配的候选人卡片'}});
  const target = picked.el.closest('a[href],button,[role=button]') || picked.el.querySelector('a[href],button,[role=button]') || picked.el;
  target.scrollIntoView({{block:'center'}});
  target.click();
  return JSON.stringify({{ok:true, score:picked.score, text:picked.t.slice(0,180)}});
}})()
"""
    try:
        return json.loads(eval_page(ws, expression) or "{}")
    except Exception as e:
        return {"ok": False, "error": str(e)}


def detail_matches_card(card, detail):
    checks = []
    if card.get("age") and detail.get("age"):
        checks.append(card.get("age") == detail.get("age"))
    if card.get("education") and detail.get("education"):
        checks.append(card.get("education") == detail.get("education"))
    if card.get("status") and detail.get("status"):
        checks.append(card.get("status") == detail.get("status"))
    return not checks or sum(1 for x in checks if x) >= max(1, len(checks) - 1)


def merge_card_detail(card, detail):
    if not detail:
        row = dict(card)
        row["detail_opened"] = False
        return row
    row = dict(card)
    for key in ["name", "phone", "email", "wechat", "education", "age", "age_years", "gender", "basic_info", "status", "job_desc", "matched_experience"]:
        row[key] = detail.get(key) or row.get(key, "")
    for key in ["resume", "raw_text", "source_url", "source_title", "resume_key", "local_pdf_path"]:
        if detail.get(key):
            row[key] = detail.get(key)
    row["detail_opened"] = True
    return row


def build_final_candidate_decision(card, detail, job_keywords):
    row = merge_card_detail(card, detail)
    row["source_url"] = row.get("source_url") or card.get("source_url", "")
    m = semantic_match_score(row, job_keywords)
    row.update(m)
    evidence = matched_experience(row.get("resume", "") or row.get("raw_text", ""), job_keywords)
    if evidence:
        row["matched_experience"] = evidence
    row["work_trace"] = json.dumps(build_trace(row, job_keywords, row.get("source_url", "")), ensure_ascii=False)
    return row


def open_candidate_detail(ws, start_page, candidate, job_keywords, platform="zhaopin"):
    start_url = start_page.get("url", "")
    start_text = start_page.get("text", "")
    href = find_candidate_href(start_page, candidate, platform)
    try:
        if href:
            ws.call("Page.navigate", {"url": href}, timeout=5)
        else:
            clicked = click_candidate_card(ws, candidate)
            if not clicked.get("ok"):
                clicked = click_candidate_by_name(ws, candidate.get("name", ""), candidate.get("name_occurrence", 0))
            if not clicked.get("ok"):
                return None, clicked.get("error") or "未找到可点击的候选人卡片"
        page = wait_page_changed(ws, start_url, start_text)
        detail = extract_candidate(page, job_keywords)
        if not detail_matches_card(candidate, detail):
            return None, f"详情页疑似打开到其他候选人：卡片 {candidate.get('name','')} {candidate.get('age','')}岁 {candidate.get('education','')}，详情 {detail.get('name','')} {detail.get('age','')}岁 {detail.get('education','')}"
        detail["source_url"] = page.get("url", "")
        detail["source_title"] = page.get("title", "")
        detail["resume_key"] = extract_resume_key(page.get("url", ""))
        if platform == "zhaopin":
            prospective = merge_card_detail(candidate, detail)
            if candidate.get("matched") or semantic_match_score(prospective, job_keywords).get("matched"):
                try:
                    pdf = zhaopin_export_current_pdf(ws, prospective)
                    if pdf.get("ok"):
                        detail["local_pdf_path"] = pdf.get("path", "")
                    else:
                        detail["pdf_error"] = pdf.get("error", "")
                except Exception as e:
                    detail["pdf_error"] = str(e)
        return detail, ""
    except Exception as e:
        return None, str(e)
    finally:
        try:
            if start_url:
                ws.call("Page.navigate", {"url": start_url}, timeout=5)
                read_recommend_page_when_ready(ws, 4)
        except Exception:
            pass


def save_candidate(candidate):
    name = (candidate.get("name") or "").strip()
    phone = (candidate.get("phone") or "").strip()
    email = (candidate.get("email") or "").strip()
    wechat = (candidate.get("wechat") or "").strip()
    education = (candidate.get("education") or "").strip()
    age = (candidate.get("age") or "").strip()
    age_years = (candidate.get("age_years") or "").strip()
    gender = (candidate.get("gender") or "").strip()
    basic_info = (candidate.get("basic_info") or "").strip()
    status = (candidate.get("status") or "").strip()
    job_desc = (candidate.get("job_desc") or "").strip()
    hit_exp = (candidate.get("matched_experience") or "").strip()
    resume = (candidate.get("resume") or candidate.get("raw_text") or "").strip()
    work_trace = candidate.get("work_trace", "") or ""
    source_url = candidate.get("source_url", "") or ""
    resume_key = candidate.get("resume_key", "") or extract_resume_key(source_url)
    local_pdf_path = candidate.get("local_pdf_path", "") or ""
    if not (name or phone or resume):
        return None
    with sqlite3.connect(DB_PATH) as con:
        if phone:
            row = con.execute("SELECT id FROM candidates WHERE phone=? LIMIT 1", (phone,)).fetchone()
            if row:
                con.execute("UPDATE candidates SET name=?, phone=?, email=?, wechat=?, education=?, age=?, age_years=?, gender=?, basic_info=?, status=?, job_desc=?, matched_experience=?, resume=?, raw_text=?, work_trace=?, source_url=?, resume_key=COALESCE(NULLIF(?,''), resume_key), local_pdf_path=COALESCE(NULLIF(?,''), local_pdf_path) WHERE id=?", (name, phone, email, wechat, education, age, age_years, gender, basic_info, status, job_desc, hit_exp, resume, resume, work_trace, source_url, resume_key, local_pdf_path, row[0]))
                return row[0]
        if resume_key:
            row = con.execute("SELECT id FROM candidates WHERE resume_key=? LIMIT 1", (resume_key,)).fetchone()
            if row:
                con.execute("UPDATE candidates SET name=?, phone=COALESCE(NULLIF(?,''), phone), email=?, wechat=?, education=?, age=?, age_years=?, gender=?, basic_info=?, status=?, job_desc=?, matched_experience=?, resume=?, raw_text=?, work_trace=?, source_url=?, local_pdf_path=COALESCE(NULLIF(?,''), local_pdf_path) WHERE id=?", (name, phone, email, wechat, education, age, age_years, gender, basic_info, status, job_desc, hit_exp, resume, resume, work_trace, source_url, local_pdf_path, row[0]))
                return row[0]
        cur = con.execute(
            "INSERT INTO candidates (created_at,name,phone,email,wechat,education,age,age_years,gender,basic_info,status,job_desc,matched_experience,resume,raw_text,work_trace,source_url,resume_key,local_pdf_path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), name, phone, email, wechat, education, age, age_years, gender, basic_info, status, job_desc, hit_exp, resume, resume, work_trace, source_url, resume_key, local_pdf_path),
        )
        return cur.lastrowid


def delete_candidate(cid):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("DELETE FROM candidates WHERE id=?", (int(cid),))
        return cur.rowcount > 0


def clear_candidates():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM candidates")
    return True


def collect_recommendations(ws_url="", job_keywords="", limit=DEFAULT_COLLECT_LIMIT, run_id="default", platform="zhaopin"):
    p = get_platform(platform)
    set_progress(run_id, total=0, current=0, message=f"开始寻找{p['name']}页面", items=[], done=False)
    if not ws_url:
        tab = find_recommend_tab(p["id"])
        if not tab:
            set_progress(run_id, message=f"未找到{p['name']}页面", done=True)
            return {"saved": [], "skipped": [{"reason": f"未找到{p['name']}页面，请先打开对应招聘平台候选人/推荐页"}], "match_report": {"total": 0, "matched": 0, "percent": 0, "items": []}, "page_url": ""}
        ws_url = tab["ws"]
    ws = CdpWebSocket(ws_url)
    saved, skipped = [], []
    try:
        start_page, ready_cards = read_recommend_page_when_ready(ws)
        page_url = start_page.get("url", "")
        if not platform_matches_url(p["id"], page_url):
            set_progress(run_id, message=f"当前页不是{p['name']}页面", done=True)
            return {"saved": [], "skipped": [{"reason": f"当前页不是{p['name']}页面：{page_url}"}], "match_report": {"total": 0, "matched": 0, "percent": 0, "items": []}, "page_url": page_url}
        if len(ready_cards) < 3:
            set_progress(run_id, total=len(ready_cards), current=0, message="候选人列表未加载完成", items=ready_cards, done=True)
            return {"saved": [], "skipped": [{"reason": f"候选人列表未加载完成或识别失败：仅识别到 {len(ready_cards)} 人"}], "match_report": {"total": len(ready_cards), "matched": 0, "percent": 0, "items": ready_cards}, "page_url": page_url}
        cards = extract_recommendation_cards(start_page.get("text", ""), job_keywords)
        if cards:
            report = build_match_report(cards[:limit], job_keywords)
            progress_items = []
            final_items = []
            set_progress(run_id, total=len(report["items"]), current=0, message="已识别推荐卡片，准备打开完整简历", items=progress_items, done=False)
            for idx, cand in enumerate(report["items"], 1):
                set_progress(run_id, total=len(report["items"]), current=idx, message=f"正在打开完整简历：{cand.get('name','')}", items=progress_items, done=False)
                detail, err = open_candidate_detail(ws, start_page, cand, job_keywords, p["id"])
                row = build_final_candidate_decision(cand, detail, job_keywords)
                row["source_url"] = row.get("source_url") or start_page.get("url", "")
                final_items.append(row)
                if row.get("matched"):
                    cid = save_candidate(row)
                    saved.append({"id": cid, "name": row.get("name", ""), "phone": row.get("phone", ""), "score": row.get("score", 0), "reason": row.get("reason", ""), "detail_opened": row.get("detail_opened", False), "has_pdf": bool(row.get("local_pdf_path"))})
                    progress_items.append({"name": row.get("name", ""), "phone": row.get("phone", ""), "status": "已入库" + ("｜PDF已保存" if row.get("local_pdf_path") else ""), "detail_opened": row.get("detail_opened", False)})
                    if err:
                        skipped.append({"name": cand.get("name", ""), "reason": "详情打开失败，已保存推荐页摘要：" + err})
                else:
                    reason = err or row.get("reason", "相关职业经历不匹配")
                    skipped.append({"name": cand.get("name", ""), "reason": reason})
                    progress_items.append({"name": cand.get("name", ""), "status": "不符合", "reason": reason})
                set_progress(run_id, total=len(report["items"]), current=idx, message=f"已处理：{cand.get('name','')}", items=progress_items, done=False)
            final_report = {"total": len(final_items), "matched": sum(1 for x in final_items if x.get("matched")), "percent": round(100 * sum(1 for x in final_items if x.get("matched")) / len(final_items)) if final_items else 0, "items": final_items}
            set_progress(run_id, total=len(final_items), current=len(final_items), message=f"采集完成：入库 {len(saved)} 人", items=progress_items, done=True)
            return {"saved": saved, "skipped": skipped, "total_links": len(saved), "match_report": final_report, "page_url": page_url}
        report = build_match_report([], job_keywords)
        set_progress(run_id, message="未识别到推荐候选人卡片", done=True)
        return {"saved": [], "skipped": [{"reason": "当前页未识别到推荐候选人卡片，请确认选中的是智联推荐人才页"}], "total_links": 0, "match_report": report}
        raw_links = start_page.get("links", [])
        links, seen = [], set()
        for link in raw_links:
            href = link.get("href")
            if href and href not in seen and looks_candidate_link(link, p["id"]):
                seen.add(href); links.append(href)
            if len(links) >= limit:
                break
        if not links:
            cards = extract_recommendation_cards(start_page.get("text", ""), job_keywords)
            report = build_match_report(cards[:limit], job_keywords)
            for cand in report["items"]:
                if not cand["matched"]:
                    skipped.append({"name": cand.get("name", ""), "reason": cand.get("reason", "")})
                    continue
                cand["source_url"] = start_page.get("url", "")
                cand["work_trace"] = json.dumps(build_trace(cand, job_keywords, start_page.get("url", "")), ensure_ascii=False)
                cid = save_candidate(cand)
                saved.append({"id": cid, "name": cand["name"], "phone": cand["phone"], "score": cand["score"], "reason": cand["reason"]})
            return {"saved": saved, "skipped": skipped or [{"reason": "当前页未识别到符合要求的候选人"}], "total_links": 0, "match_report": report}
        for href in links:
            try:
                ws.call("Page.navigate", {"url": href}, timeout=5)
                time.sleep(1.5)
                page = read_current_page(ws)
                cand = extract_candidate(page, job_keywords)
                if cand["suitable"] and (cand["phone"] or cand.get("matched_experience")):
                    cid = save_candidate(cand)
                    saved.append({"id": cid, "name": cand["name"], "phone": cand["phone"]})
                else:
                    skipped.append({"url": href, "reason": "无电话或不命中关键词"})
            except Exception as e:
                skipped.append({"url": href, "reason": str(e)})
    finally:
        ws.close()
    return {"saved": saved, "skipped": skipped[:20], "total_links": len(links)}


def list_candidates():
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("SELECT id,created_at,name,phone,email,wechat,education,age,age_years,gender,basic_info,status,job_desc,matched_experience,COALESCE(NULLIF(resume,''),raw_text) AS resume,work_trace,source_url,resume_key,local_pdf_path FROM candidates ORDER BY id DESC")
        return [build_display_row(x) for x in rows_to_dicts(cur)]


def get_candidate(cid):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("SELECT id,created_at,name,phone,email,wechat,education,age,age_years,gender,basic_info,status,job_desc,matched_experience,COALESCE(NULLIF(resume,''),raw_text) AS resume,work_trace,source_url,resume_key,local_pdf_path FROM candidates WHERE id=? LIMIT 1", (int(cid),))
        rows = rows_to_dicts(cur)
        return build_display_row(rows[0]) if rows else None


def generate_candidate_pdf(cid):
    row = get_candidate(cid)
    if not row:
        raise RuntimeError("候选人不存在")
    source_url = row.get("source_url") or ""
    if "zhaopin.com" not in source_url or not extract_resume_key(source_url):
        raise RuntimeError("缺少智联简历链接，无法补生成 PDF")
    tab = find_recommend_tab("zhaopin") or (cdp_tabs()[0] if cdp_tabs() else None)
    if not tab:
        raise RuntimeError("未连接受控浏览器，请先打开招聘平台浏览器")
    ws = CdpWebSocket(tab["ws"])
    try:
        ws.call("Page.navigate", {"url": source_url}, timeout=8)
        wait_page_changed(ws, "", "", wait_seconds=8)
        pdf = zhaopin_export_current_pdf(ws, row)
    finally:
        ws.close()
    if not pdf.get("ok"):
        raise RuntimeError(pdf.get("error") or "PDF 生成失败")
    with sqlite3.connect(DB_PATH) as con:
        con.execute("UPDATE candidates SET local_pdf_path=?, resume_key=COALESCE(NULLIF(resume_key,''), ?) WHERE id=?", (pdf["path"], extract_resume_key(source_url), int(cid)))
    return {"ok": True, "id": int(cid), "local_pdf_path": pdf["path"]}


def dedupe_candidates():
    rows = list_candidates()
    seen, delete_ids = set(), []
    for r in rows:
        key = r.get("phone") or r.get("resume_key") or "|".join([r.get("name", ""), r.get("age", ""), r.get("education", ""), (r.get("resume", "") or "")[:80]])
        if not key.strip("|"):
            continue
        if key in seen:
            delete_ids.append(r["id"])
        else:
            seen.add(key)
    with sqlite3.connect(DB_PATH) as con:
        for cid in delete_ids:
            con.execute("DELETE FROM candidates WHERE id=?", (cid,))
    return {"ok": True, "deleted": len(delete_ids)}


def limit_lines(text, max_lines):
    return "\n".join(clean_lines(text)[:max_lines])


def clean_basic_profile(text):
    noise = ["小时前", "分钟前", "有投递", "最近关注", "打电话", "打招呼", "推荐", "查看", "沟通", "活跃"]
    lines = []
    for line in clean_lines(text):
        if any(n in line for n in noise):
            continue
        if re.match(r"^[\u4e00-\u9fa5]{1,4}(先生|女士)$", line):
            continue
        if line not in lines:
            lines.append(line)
    return "\n".join(lines[:6])


def compose_profile_summary(profile_text, matched_text, row=None):
    row = row or {}
    profile_lines = []
    for label, key in [("年龄", "age"), ("性别", "gender"), ("学历", "education"), ("求职状态", "status")]:
        value = (row.get(key) or "").strip()
        if value:
            profile_lines.append(f"{label}：{value}")
    profile = "\n".join(profile_lines) or clean_basic_profile(profile_text)
    matched = limit_lines(matched_text or "", 5)
    parts = []
    if profile:
        parts.append(profile)
    if matched:
        parts.append("符合要求经历：\n" + matched)
    return "\n".join(parts)


def build_display_row(row):
    d = dict(row)
    if not d.get("resume_key"):
        d["resume_key"] = extract_resume_key(d.get("source_url", ""))
    matched = limit_lines(row.get("matched_experience", "") or "", 5)
    summary_src = row.get("basic_info", "") or row.get("resume", "")
    d["profile_summary"] = compose_profile_summary(summary_src, matched, row)
    d["match_excerpt"] = matched or "已打开完整简历，但暂未提取到明确匹配经历"
    d["has_pdf"] = bool(row.get("local_pdf_path") and Path(row.get("local_pdf_path", "")).exists())
    return d


def csv_phone_text(phone):
    phone = (phone or "").strip()
    return f'="{phone}"' if phone else ""


def build_export_row(row):
    trace = row.get("work_trace", "") or ""
    try:
        trace_obj = json.loads(trace) if trace else {}
    except Exception:
        trace_obj = {}
    requirements = trace_obj.get("requirements", "") or row.get("matched", "")
    match = semantic_match_score(row, requirements) if requirements else {"score": "", "reason": "未输入关键词"}
    resume = row.get("resume", "") or ""
    matched = limit_lines(row.get("matched_experience", "") or "", 5)
    summary = row.get("basic_info", "") or "\n".join([x for x in clean_lines(resume) if x not in clean_lines(matched)][:10])
    return {
        "姓名": row.get("name", "") or "未识别",
        "电话": csv_phone_text(row.get("phone", "")),
        "工作经历匹配度": f"{match['score']}%" if match.get("score") != "" else "",
        "匹配说明": match.get("reason", ""),
        "相关经历": matched or "未提取到明确相关经历",
        "年龄": row.get("age", ""),
        "性别": row.get("gender", ""),
        "学历": row.get("education", "") or "未识别",
        "求职状态": row.get("status", ""),
        "微信": row.get("wechat", ""),
        "邮箱": row.get("email", ""),
        "个人基本资料": compose_profile_summary(summary, matched, row),
    }


def build_csv_bytes(rows):
    from io import StringIO
    sio = StringIO()
    writer = csv.DictWriter(sio, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(build_export_row(row))
    return sio.getvalue().encode("utf-8-sig")


def col_name(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def xcell(ref, value, style=0):
    value = "" if value is None else str(value)
    style_attr = f' s="{style}"' if style else ""
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t>{xml_utils.escape(value)}</t></is></c>'


def build_xlsx_bytes(rows):
    export_rows = []
    for row in rows:
        base = build_export_row(row)
        export_rows.append({"跟进状态": "待联系", "优先级": "B", "最近跟进时间": "", "跟进人": "", "备注": "", **base})
    widths = [14, 10, 18, 12, 36, 12, 16, 18, 26, 8, 16, 10, 18, 30, 42, 36, 50]
    headers = "".join(xcell(f"{col_name(i)}1", h, 1) for i, h in enumerate(XLSX_FIELDS, 1))
    sheet_rows = [f'<row r="1" ht="28" customHeight="1">{headers}</row>']
    for r, row in enumerate(export_rows, 2):
        style = 3 if not (row.get("电话") or row.get("微信") or row.get("邮箱")) else 0
        cells = "".join(xcell(f"{col_name(c)}{r}", row.get(h, ""), style) for c, h in enumerate(XLSX_FIELDS, 1))
        sheet_rows.append(f'<row r="{r}">{cells}</row>')
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, 1))
    last_col = col_name(len(XLSX_FIELDS)); last_row = max(1, len(export_rows) + 1)
    sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetViews><sheetView workbookViewId="0"><pane xSplit="6" ySplit="1" topLeftCell="G2" activePane="bottomRight" state="frozen"/></sheetView></sheetViews>
<cols>{cols}</cols><sheetData>{"".join(sheet_rows)}</sheetData>
<autoFilter ref="A1:{last_col}{last_row}"/>
</worksheet>'''
    styles_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="11"/><name val="Microsoft YaHei"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Microsoft YaHei"/></font></fonts>
<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1E3A8A"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFFEE2E2"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellXfs count="4"><xf fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf><xf fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf fontId="0" fillId="0" borderId="0" xfId="0"/><xf fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf></cellXfs>
</styleSheet>'''
    from io import BytesIO
    bio = BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>''')
        z.writestr("_rels/.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
        z.writestr("xl/workbook.xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="候选人台账" sheetId="1" r:id="rId1"/></sheets></workbook>''')
        z.writestr("xl/_rels/workbook.xml.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''')
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        z.writestr("xl/styles.xml", styles_xml)
    return bio.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8", "replace")) if length else {}

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        try:
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                self.serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            elif path == "/api/health":
                self.send_json({
                    "ok": True,
                    "port": APP_PORT,
                    "db": str(DB_PATH),
                    "browser_found": bool(find_browser()),
                    "export_fields": EXPORT_FIELDS,
                    "platforms": [{"id": v["id"], "name": v["name"]} for v in PLATFORMS.values()],
                })
            elif path == "/api/tabs":
                self.send_json({"tabs": cdp_tabs()})
            elif path == "/api/candidates":
                self.send_json({"candidates": list_candidates()})
            elif path == "/api/progress":
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                self.send_json(get_progress((qs.get("run") or ["default"])[0]))
            elif path == "/api/candidate-pdf":
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                self.serve_candidate_pdf((qs.get("id") or [""])[0])
            elif path == "/export.csv":
                self.export_csv()
            elif path == "/export.xlsx":
                self.export_xlsx()
            else:
                self.send_json({"error": "not found"}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def do_POST(self):
        try:
            path = urllib.parse.urlparse(self.path).path
            body = self.read_json()
            if path == "/api/launch-browser":
                self.send_json(launch_browser(body.get("platform", "zhaopin")))
            elif path == "/api/capture":
                self.send_json(capture_tab(body.get("ws", ""), body.get("keywords", "")))
            elif path == "/api/collect-recommendations":
                self.send_json(collect_recommendations(body.get("ws", ""), body.get("keywords", ""), int(body.get("limit", DEFAULT_COLLECT_LIMIT)), body.get("run", "default"), body.get("platform", "zhaopin")))
            elif path == "/api/import-text":
                candidates = extract_candidates_from_text(body.get("text", ""), body.get("keywords", ""))
                ids = [save_candidate(c) for c in candidates if c.get("phone")]
                self.send_json({"ok": True, "saved": len([x for x in ids if x]), "candidates": candidates})
            elif path == "/api/candidates":
                self.send_json({"ok": True, "id": save_candidate(body)})
            elif path == "/api/delete-candidate":
                self.send_json({"ok": delete_candidate(body.get("id"))})
            elif path == "/api/clear-candidates":
                self.send_json({"ok": clear_candidates()})
            elif path == "/api/generate-candidate-pdf":
                self.send_json(generate_candidate_pdf(body.get("id")))
            elif path == "/api/dedupe-candidates":
                self.send_json(dedupe_candidates())
            else:
                self.send_json({"error": "not found"}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def serve_file(self, path, content_type):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def serve_candidate_pdf(self, cid):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        row = get_candidate(cid)
        pdf = Path((row or {}).get("local_pdf_path") or "")
        try:
            pdf = pdf.resolve()
            if not str(pdf).startswith(str(PDF_DIR.resolve())) or not pdf.exists():
                self.send_json({"error": "该候选人还没有可预览的本地 PDF"}, 404)
                return
            body = pdf.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            mode = "attachment" if (qs.get("download") or ["0"])[0] == "1" else "inline"
            self.send_header("Content-Disposition", f"{mode}; filename=resume-{cid}.pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def export_csv(self):
        body = build_csv_bytes(list_candidates())
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", "attachment; filename=hr_resume_ledger.csv")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def export_xlsx(self):
        body = build_xlsx_bytes(list_candidates())
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", "attachment; filename=hr_resume_ledger.xlsx")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)


def main():
    init_db()
    server = ThreadingHTTPServer((APP_HOST, APP_PORT), Handler)
    open_host = "127.0.0.1" if APP_HOST in ("0.0.0.0", "::") else APP_HOST
    url = f"http://{open_host}:{APP_PORT}"
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"HR简历台账已启动：{url}")
    print("关闭此窗口即可停止服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
