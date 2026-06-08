import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app


def test_extract_candidate_required_fields_only_contract():
    page = {
        "title": "张三 - 智联招聘",
        "url": "https://ihr.zhaopin.com/resume/1",
        "text": "张三\n电话：13800138000\n本科\n5年Python和SQL经验\n完整简历内容在这里",
    }
    c = app.extract_candidate(page, "Python, SQL")
    assert c["name"] == "张三"
    assert c["phone"] == "13800138000"
    assert "完整简历内容" in c["resume"]
    assert c["suitable"] is True


def test_export_fields_are_minimal():
    assert app.EXPORT_FIELDS == [
        "姓名", "电话", "工作经历匹配度", "匹配说明", "相关经历",
        "年龄", "性别", "学历", "求职状态", "微信", "邮箱", "个人基本资料",
    ]


def test_extract_many_candidates_from_pasted_recommendation_text():
    text = """
    张三 13800138000 Python 本科 完整简历A
    ---
    李四 手机：13900139000 SQL 数据分析 完整简历B
    """
    rows = app.extract_candidates_from_text(text, "Python SQL")
    assert [(r["name"], r["phone"]) for r in rows] == [("张三", "13800138000"), ("李四", "13900139000")]


def test_delete_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "x.sqlite3")
    app.init_db()
    cid = app.save_candidate({"name": "张三", "phone": "13800138000", "resume": "简历"})
    assert app.delete_candidate(cid) is True
    assert app.list_candidates() == []

