import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app


def test_extract_recommendation_cards_without_phone():
    text = """
吴女士
5分钟前有投递
22岁
4年
大专
在职-正在找工作
最近关注：
南京
 导医
护士
(2年)
内科
康复科
护士资格证
打电话
打招呼
苏先生
22岁
26年应届生
本科
期望：
南京
导医
6千-1万
打电话
打招呼
"""
    rows = app.extract_recommendation_cards(text, "导医 本科")
    assert rows[0]["name"] == "吴女士"
    assert rows[0]["education"] == "大专"
    assert "导医" in rows[0]["matched_experience"]
    assert any(r["name"] == "苏先生" and r["education"] == "本科" for r in rows)
    su = next(r for r in rows if r["name"] == "苏先生")
    assert su["job_desc"] == "导医"
    assert "22岁" not in su["job_desc"]


def test_find_candidate_href_matches_name():
    page = {"links": [
        {"text": "苏先生", "href": "https://rd6.zhaopin.com/app/resume/su"},
        {"text": "吴女士 查看简历", "href": "https://rd6.zhaopin.com/app/resume/wu"},
    ]}
    assert app.find_candidate_href(page, {"name": "吴女士"}) == "https://rd6.zhaopin.com/app/resume/wu"


def test_merge_card_detail_prefers_full_resume():
    row = app.merge_card_detail(
        {"name": "吴女士", "phone": "", "resume": "推荐摘要"},
        {"name": "吴女士", "phone": "13800138000", "resume": "完整简历"},
    )
    assert row["phone"] == "13800138000"
    assert row["resume"] == "完整简历"
    assert row["detail_opened"] is True
