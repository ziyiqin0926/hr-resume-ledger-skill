"""
匹配口径校准测试草案。

这些测试描述下一步应实现的行为：最终命中率必须来自“全量推荐人详情页 + 硬性条件”，
不能来自推荐页卡片关键词命中。
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app


def test_keyword_hit_does_not_equal_hard_match():
    req = app.parse_requirements("必须本科及以上；岗位：导医；年龄：22-35；加分：护士资格证")
    candidate = {
        "name": "吴女士",
        "education": "大专",
        "age": "28",
        "matched_experience": "有导医接待经历",
        "phone": "13800138000",
    }
    result = app.evaluate_candidate(candidate, req)
    assert result["hard_pass"] is False
    assert result["matched"] is False
    assert any("学历" in x for x in result["reasons"])


def test_total_uses_all_recommendation_cards_not_prefiltered_cards():
    cards = [{"name": f"候选人{i}", "resume": "销售"} for i in range(30)]
    cards[3].update({"resume": "本科 导医 护士资格证", "education": "本科", "age": "26", "phone": "13800138000"})
    cards[19].update({"resume": "本科 导医 医院分诊", "education": "本科", "age": "29", "phone": "13900139000"})
    req = app.parse_requirements("硬性：本科 导医；必须年龄：22-35")
    report = app.build_calibrated_match_report(cards, req)
    assert report["total"] == 30
    assert report["matched"] == 2
    assert report["percent"] == 7


def test_unopened_detail_cannot_be_final_match():
    req = app.parse_requirements("硬性：本科 导医 有联系方式")
    candidate = {"name": "苏先生", "resume": "本科 导医", "detail_success": False}
    result = app.evaluate_candidate(candidate, req)
    assert result["matched"] is False
    assert any("详情" in x or "未验证" in x for x in result["reasons"])


def test_semantic_experience_can_match_without_literal_keyword():
    req = app.parse_requirements("硬性：本科 导医 22-35 有联系方式；加分：护士资格证")
    candidate = {
        "name": "周女士",
        "education": "本科",
        "age": "27",
        "phone": "13800138000",
        "resume": "三年医院门诊分诊、患者接待、前台咨询经验，持有护理资格证",
        "detail_success": True,
    }
    result = app.evaluate_candidate(candidate, req)
    assert result["matched"] is True
    assert result["score"] >= 80
    assert "导医" in result["hit_terms"]


def test_missing_required_age_does_not_pass():
    req = app.parse_requirements("硬性：本科 导医；必须年龄：22-35")
    candidate = {
        "name": "周女士",
        "education": "本科",
        "phone": "13800138000",
        "resume": "医院门诊分诊、患者接待经验",
        "detail_success": True,
    }
    result = app.evaluate_candidate(candidate, req)
    assert result["matched"] is False
    assert any("年龄" in x for x in result["reasons"])


def test_cross_industry_sales_experience_semantic_match():
    req = app.parse_requirements("硬性：大专 销售顾问 客户开发 有联系方式")
    candidate = {
        "name": "陈先生",
        "education": "大专",
        "phone": "13800138000",
        "resume": "3年BD商务拓展经验，负责陌拜获客、客户转化、签单回款",
        "detail_success": True,
    }
    result = app.evaluate_candidate(candidate, req)
    assert result["matched"] is True
    assert any(x in result["hit_terms"] for x in ["销售顾问", "客户开发"])


def test_cross_industry_technical_experience_semantic_match():
    req = app.parse_requirements("硬性：本科 Python后端 API MySQL 有联系方式")
    candidate = {
        "name": "赵先生",
        "education": "本科",
        "email": "zhao@example.com",
        "resume": "负责Django REST服务开发、接口设计、数据库表结构设计和SQL优化",
        "detail_success": True,
    }
    result = app.evaluate_candidate(candidate, req)
    assert result["matched"] is True
    assert "Python后端" in result["hit_terms"]


def test_cross_industry_unrelated_experience_does_not_match():
    req = app.parse_requirements("硬性：大专 销售顾问 客户开发 有联系方式")
    candidate = {
        "name": "刘女士",
        "education": "大专",
        "phone": "13800138000",
        "resume": "2年行政文员经验，负责资料整理、会议安排、考勤统计",
        "detail_success": True,
    }
    result = app.evaluate_candidate(candidate, req)
    assert result["matched"] is False
    assert any("语义不匹配" in x for x in result["reasons"])


def test_sales_manager_related_roles_semantic_match():
    req = app.parse_requirements("硬性：大专 销售经理 团队管理 渠道拓展 有联系方式")
    candidate = {
        "name": "钱先生",
        "education": "大专",
        "phone": "13800138000",
        "resume": "5年销售主管经验，带领8人销售团队，负责渠道客户开发、业绩目标拆解、签单回款管理",
        "detail_success": True,
    }
    result = app.evaluate_candidate(candidate, req)
    assert result["matched"] is True
    assert "销售经理" in result["hit_terms"]


def test_card_summary_can_be_recovered_by_full_detail():
    card = {"name": "钱先生", "education": "大专", "resume": "销售主管", "detail_opened": False}
    detail = {
        "name": "钱先生",
        "education": "大专",
        "age": "31",
        "phone": "13800138000",
        "resume": "5年销售主管经验，带销售团队，负责渠道拓展、业绩目标拆解、签单回款",
        "detail_success": True,
    }
    row = app.build_final_candidate_decision(card, detail, "大专 销售经理 团队管理 渠道拓展 有联系方式")
    assert row["matched"] is True
    assert row["detail_opened"] is True


def test_no_phone_still_matches_by_related_industry_experience():
    req = app.parse_requirements("硬性：大专 销售经理 团队管理 渠道拓展 有联系方式")
    candidate = {
        "name": "钱先生",
        "education": "大专",
        "resume": "5年销售主管经验，带销售团队，负责渠道拓展、签单回款",
        "detail_success": True,
    }
    result = app.evaluate_candidate(candidate, req)
    assert result["matched"] is True


def test_contact_only_hard_fails_when_explicitly_required():
    req = app.parse_requirements("硬性：大专 销售经理 必须有联系方式")
    candidate = {
        "name": "钱先生",
        "education": "大专",
        "resume": "5年销售主管经验，负责销售团队管理",
        "detail_success": True,
    }
    result = app.evaluate_candidate(candidate, req)
    assert result["matched"] is False
    assert any("联系方式" in x for x in result["reasons"])


def test_common_job_description_matches_new_media_operation():
    req = app.parse_requirements("新媒体运营")
    candidate = {
        "name": "林女士",
        "resume": "负责公众号推文、短视频内容发布、社群增长、活动复盘和数据分析",
        "detail_success": True,
    }
    result = app.evaluate_candidate(candidate, req)
    assert result["matched"] is True
    assert "新媒体运营" in result["hit_terms"]


def test_common_job_description_matches_recruiter_without_literal_title():
    req = app.parse_requirements("招聘专员")
    candidate = {
        "name": "黄女士",
        "resume": "负责简历筛选、电话邀约、面试安排、offer沟通和入职跟进",
        "detail_success": True,
    }
    result = app.evaluate_candidate(candidate, req)
    assert result["matched"] is True
    assert "招聘专员" in result["hit_terms"]


def test_default_collect_limit_is_500():
    assert app.DEFAULT_COLLECT_LIMIT == 500


def test_medical_related_experience_matches_broadly():
    req = app.parse_requirements("医疗相关经历")
    rows = [
        {"resume": "中医馆从业3年，负责中药调理咨询和患者接待", "detail_success": True},
        {"resume": "西医临床门诊助理，协助医生接诊和病历整理", "detail_success": True},
        {"resume": "医院导医分诊，负责患者引导和门诊咨询", "detail_success": True},
    ]
    results = [app.evaluate_candidate(x, req) for x in rows]
    assert all(r["matched"] for r in results)
    assert all("医疗相关经历" in r["hit_terms"] for r in results)


def test_match_uses_resume_content_not_candidate_job_desc():
    req = app.parse_requirements("护士资格证 护理专业 专科")
    matched = {
        "resume": "教育经历：江苏省南通卫生高等职业技术学校，护理，专科。工作经历：梅山医院 ICU 护士，持有护士资格证、护士执业证书。",
        "job_desc": "搜索",
        "detail_success": True,
    }
    missed = {
        "resume": "销售顾问，负责客户开发和签单回款。",
        "job_desc": "护士资格证 护理专业 专科",
        "detail_success": True,
    }
    assert app.evaluate_candidate(matched, req)["matched"] is True
    assert app.evaluate_candidate(missed, req)["matched"] is False


def test_profile_summary_contains_keyword_matched_resume_evidence():
    row = app.build_final_candidate_decision({
        "name": "朱女士",
        "basic_info": "女 25岁 专科",
        "resume": "教育经历：护理，专科。工作经历：梅山医院 ICU 护士，持有护士资格证、护士执业证书。",
        "detail_success": True,
    }, None, "护士资格证 护理专业 专科")
    display = app.build_display_row(row)
    assert row["matched"] is True
    assert "护士资格证" in display["profile_summary"]
    assert "护理" in display["profile_summary"]


def test_job_title_is_not_guessed_as_name():
    assert app.guess_name(["销售经理", "负责团队管理"], "销售经理-完整简历") == ""
    assert app.guess_name(["张先生", "销售经理"], "") == "张先生"
