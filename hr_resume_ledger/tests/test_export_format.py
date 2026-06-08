import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app


def test_export_fields_follow_readable_order():
    assert app.EXPORT_FIELDS == [
        "姓名", "电话", "工作经历匹配度", "匹配说明", "相关经历",
        "年龄", "性别", "学历", "求职状态", "微信", "邮箱", "个人基本资料", "沟通回溯",
    ]


def test_build_export_row_formats_phone_and_limits_long_text():
    row = app.build_export_row({
        "name": "王五",
        "phone": "13800138000",
        "wechat": "wx_wangwu88",
        "email": "wangwu@example.com",
        "gender": "男",
        "age": "28",
        "age_years": "6年经验",
        "education": "本科",
        "status": "在职-看看机会",
        "job_desc": "导医",
        "matched_experience": "\n".join([f"经历{i}" for i in range(8)]),
        "basic_info": "\n".join([f"信息{i}" for i in range(12)]),
        "work_trace": '{"requirements":"导医 本科"}',
    })
    assert row["电话"] == '="13800138000"'
    assert row["年龄"] == "28"
    assert row["相关经历"].count("\n") == 4
    assert "符合要求经历" in row["个人基本资料"]
    assert "年龄：28" in row["个人基本资料"]
    assert "学历：本科" in row["个人基本资料"]


def test_export_basic_profile_is_readable_and_noise_free():
    row = app.build_export_row({
        "name": "王五",
        "phone": "13800138000",
        "age": "28",
        "gender": "男",
        "education": "本科",
        "status": "在职-看看机会",
        "basic_info": "3小时前有投递\n男 28岁 本科\n现居住地：合肥\n打电话\n最近关注：南京",
        "matched_experience": "5年销售团队管理经验",
        "work_trace": '{"requirements":"销售经理"}',
    })
    assert row["年龄"] == "28"
    assert "3小时前" not in row["个人基本资料"]
    assert "打电话" not in row["个人基本资料"]
    assert "年龄：28" in row["个人基本资料"]
    assert "性别：男" in row["个人基本资料"]
    assert "学历：本科" in row["个人基本资料"]


def test_display_summary_prioritizes_matched_resume_excerpt():
    row = app.build_display_row({
        "name": "朱女士",
        "age": "25",
        "education": "硕士",
        "basic_info": "朱女士\n25岁\n打电话\n杨女士",
        "matched_experience": "曾在中医馆负责患者接待、中药调理咨询，熟悉门诊导诊流程。",
        "resume": "完整简历内容",
    })
    assert row["match_excerpt"] == "曾在中医馆负责患者接待、中药调理咨询，熟悉门诊导诊流程。"
    assert "打电话" not in row["profile_summary"]
    assert "杨女士" not in row["profile_summary"]


def test_profile_summary_includes_matched_experience_for_ledger():
    row = app.build_display_row({
        "name": "朱女士",
        "age": "25",
        "education": "硕士",
        "basic_info": "女 25岁 硕士\n现居住地：南通",
        "matched_experience": "梅山医院 ICU 重症监护室护士，具备护士资格证和公立医院经历。",
    })
    assert "符合要求经历" in row["profile_summary"]
    assert "ICU 重症监护室护士" in row["profile_summary"]
    export_row = app.build_export_row(row)
    assert "ICU 重症监护室护士" in export_row["个人基本资料"]


def test_export_profile_summary_is_structured_not_raw_expectation_noise():
    row = app.build_export_row({
        "name": "李女士",
        "age": "28",
        "education": "大专",
        "status": "在职-看看机会",
        "basic_info": "期望\n28岁\n41岁\n打电话\n最近关注：南京",
        "matched_experience": "曾在门诊负责导诊、分诊和患者接待。",
        "resume": "完整简历",
    })
    profile = row["个人基本资料"]
    assert "年龄：28" in profile
    assert "学历：大专" in profile
    assert "求职状态：在职-看看机会" in profile
    assert "符合要求经历" in profile
    assert "期望" not in profile
    assert "41岁" not in profile
    assert "打电话" not in profile


def test_profile_summary_uses_full_resume_basic_info_and_keyword_evidence():
    row = app.build_final_candidate_decision({
        "name": "李女士",
        "age": "23",
        "education": "大专",
        "status": "离校-正在找工作",
        "basic_info": "23岁 大专 离校-正在找工作 现居南阳 邓州市",
        "resume": """
求职期望 医生助理 临床医生
工作经历
邓州市人民医院 执业助理医师（临床医生）
医师资格证书 医师执业证书 助理医师 公立医院 二甲医院
协助主任医师完成临床治疗及手术相关事宜，提供患者陪同、就诊引导等导诊服务。
教育经历
河南医学高等专科学校 临床医学 大专
所获证书
助理医师执业证（临床） 助理医师资格证（临床）
""",
        "detail_success": True,
    }, None, "临床医生 助理医师 大专")
    profile = app.build_export_row(row)["个人基本资料"]
    assert "年龄：23" in profile
    assert "学历：大专" in profile
    assert "求职状态：离校-正在找工作" in profile
    assert "执业助理医师" in profile
    assert "临床医学 大专" in profile
    assert "求职期望" not in profile


def test_export_row_prioritizes_keywords_and_work_experience_match():
    row = app.build_export_row({
        "name": "王五",
        "phone": "13800138000",
        "education": "大专",
        "matched_experience": "有导医接待经验",
        "resume": "有导医接待经验",
        "work_trace": '{"requirements":"导医 本科"}',
    })
    assert "输入关键词" not in row
    assert row["工作经历匹配度"] == "80%"
    assert "导医" in row["匹配说明"]


def test_csv_export_uses_new_order_and_phone_text_format():
    rows = [{"name": "王五", "phone": "13800138000", "work_trace": '{"requirements":"导医"}'}]
    body = app.build_csv_bytes(rows).decode("utf-8-sig")
    parsed = list(csv.DictReader(io.StringIO(body)))
    assert parsed[0]["电话"] == '="13800138000"'
    assert list(parsed[0].keys())[:4] == ["姓名", "电话", "工作经历匹配度", "匹配说明"]
