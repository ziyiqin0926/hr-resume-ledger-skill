import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app


def test_extract_precise_candidate_fields_and_matching_experience():
    page = {"title": "张三 - 智联", "url": "u", "text": """
张三
手机：13800138000
本科
工作经历
2021-2024 ABC公司 数据分析师，负责 Python SQL 数据建模和报表自动化
2019-2021 DEF公司 销售助理，负责客户跟进
"""}
    c = app.extract_candidate(page, "Python SQL 数据分析 本科")
    assert c["name"] == "张三"
    assert c["phone"] == "13800138000"
    assert c["education"] == "本科"
    assert "Python SQL" in c["matched_experience"]
    assert "销售助理" not in c["matched_experience"]


def test_filter_by_requirements_positive_and_negative():
    good = {"text": "张三 13800138000 本科 2021-2024 数据分析师 Python SQL"}
    bad = {"text": "李四 13900139000 高中 2021-2024 销售"}
    assert app.matches_requirements(good, "Python SQL 本科") is True
    assert app.matches_requirements(bad, "Python SQL 本科") is False


def test_export_fields_are_precise():
    assert app.EXPORT_FIELDS == [
        "姓名", "电话", "工作经历匹配度", "匹配说明", "相关经历",
        "年龄", "性别", "学历", "求职状态", "微信", "邮箱", "个人基本资料", "沟通回溯",
    ]
