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
        "年龄", "性别", "学历", "求职状态", "微信", "邮箱", "个人基本资料", "沟通回溯",
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


def test_candidate_pdf_path_is_stored_and_marked(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "x.sqlite3")
    monkeypatch.setattr(app, "PDF_DIR", tmp_path / "resume_pdfs")
    app.PDF_DIR.mkdir()
    pdf = app.PDF_DIR / "张三.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    app.init_db()
    app.save_candidate({"name": "张三", "phone": "13800138000", "resume": "简历", "local_pdf_path": str(pdf)})
    row = app.list_candidates()[0]
    assert row["local_pdf_path"] == str(pdf)
    assert row["has_pdf"] is True


def test_save_candidate_dedupes_by_resume_key_without_phone(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "x.sqlite3")
    app.init_db()
    url = "https://rd6.zhaopin.com/app/recommend?jobNumber=J1&resumeNumber=R1"
    a = app.save_candidate({"name": "张先生", "resume": "简历A", "source_url": url})
    b = app.save_candidate({"name": "张先生", "resume": "简历B", "source_url": url})
    rows = app.list_candidates()
    assert a == b
    assert len(rows) == 1
    assert rows[0]["resume_key"] == "J1|R1"


def test_same_resume_key_is_strictly_deduped(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "x.sqlite3")
    app.init_db()
    url = "https://rd6.zhaopin.com/app/recommend?jobNumber=J1&resumeNumber=R1"
    app.save_candidate({"name": "张先生", "age": "22", "resume": "简历A", "source_url": url})
    app.save_candidate({"name": "李女士", "age": "33", "resume": "简历B", "source_url": url})
    rows = app.list_candidates()
    assert len(rows) == 1
    assert rows[0]["name"] == "李女士"


def test_card_only_candidates_do_not_dedupe_by_list_url(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "x.sqlite3")
    app.init_db()
    url = "https://rd6.zhaopin.com/app/recommend?jobNumber=J1&resumeNumber=R1"
    app.save_candidate({"name": "张先生", "age": "22", "resume": "建筑设计", "source_url": url, "detail_opened": False})
    app.save_candidate({"name": "李女士", "age": "33", "resume": "建筑设计", "source_url": url, "detail_opened": False})
    rows = app.list_candidates()
    assert len(rows) == 2
    assert all(not r["resume_key"] for r in rows)


def test_related_experience_enters_ledger_for_review():
    row = {"matched": False, "score": 35, "matched_experience": "做过建筑方案设计", "detail_opened": True, "reason": "", "phone": "13800138000"}
    assert app.should_enter_ledger(row) is True
    assert "待复核" in row["reason"]


def test_related_experience_without_backtrack_anchor_is_not_ledgered():
    row = {"matched": True, "score": 80, "matched_experience": "做过建筑方案设计", "detail_opened": True, "reason": ""}
    assert app.should_enter_ledger(row) is False
    assert "缺少联系方式/PDF/原简历直达锚点" in row["reason"]


def test_zhaopin_resume_url_is_backtrack_anchor():
    row = {
        "matched": True,
        "score": 80,
        "matched_experience": "做过建筑方案设计",
        "detail_opened": True,
        "reason": "",
        "source_url": "https://rd6.zhaopin.com/app/recommend?jobNumber=J1&resumeNumber=R1",
    }
    assert app.should_enter_ledger(row) is True
    assert "原简历可直达" in row["reason"]


def test_zhaopin_candidate_with_resume_link_can_enter_without_pdf():
    row = {
        "matched": True,
        "score": 80,
        "matched_experience": "做过建筑方案设计",
        "detail_opened": True,
        "reason": "",
        "pdf_required": True,
        "source_url": "https://rd6.zhaopin.com/app/recommend?jobNumber=J1&resumeNumber=R1",
    }
    assert app.should_enter_ledger(row) is True
    assert "原简历可直达" in row["reason"]


def test_zhaopin_candidate_without_any_backtrack_route_is_blocked():
    row = {
        "matched": True,
        "score": 80,
        "matched_experience": "做过建筑方案设计",
        "detail_opened": True,
        "reason": "",
        "pdf_required": True,
    }
    assert app.should_enter_ledger(row) is False
    assert "缺少联系方式/PDF/原简历直达锚点" in row["reason"]


def test_zhaopin_candidate_with_local_pdf_can_enter_ledger(tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    row = {
        "matched": True,
        "score": 80,
        "matched_experience": "做过建筑方案设计",
        "detail_opened": True,
        "reason": "",
        "pdf_required": True,
        "local_pdf_path": str(pdf),
        "source_url": "https://rd6.zhaopin.com/app/recommend?jobNumber=J1&resumeNumber=R1",
    }
    assert app.should_enter_ledger(row) is True
    assert "PDF已保存" in row["reason"]


def test_sync_candidate_pdfs_uses_zhaopin_resume_link(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "x.sqlite3")
    monkeypatch.setattr(app, "PDF_DIR", tmp_path / "resume_pdfs")
    app.PDF_DIR.mkdir()
    app.init_db()
    cid = app.save_candidate({
        "name": "张先生",
        "phone": "13800138000",
        "resume": "建筑方案设计",
        "source_url": "https://rd6.zhaopin.com/app/recommend?jobNumber=J1&resumeNumber=R1",
    })
    pdf = app.PDF_DIR / "张先生.pdf"

    def fake_generate(row_id):
        assert row_id == cid
        pdf.write_bytes(b"%PDF-1.4\n")
        with app.sqlite3.connect(app.DB_PATH) as con:
            con.execute("UPDATE candidates SET local_pdf_path=? WHERE id=?", (str(pdf), row_id))
        return {"ok": True, "id": row_id, "local_pdf_path": str(pdf)}

    monkeypatch.setattr(app, "generate_candidate_pdf", fake_generate)
    result = app.sync_candidate_pdfs()
    assert result["synced"] == 1
    assert app.list_candidates()[0]["has_pdf"] is True


def test_resume_text_dedupes_repeated_paragraphs():
    text = "工作经历\nA公司\n负责建筑方案设计\n负责建筑方案设计\n教育经历\nA公司\n负责建筑方案设计"
    cleaned = app.dedupe_resume_text(text)
    assert cleaned.count("负责建筑方案设计") == 1
    assert "工作经历" in cleaned


def test_frontend_prefers_pdf_preview():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "/api/candidate-pdf?id=" in html
    assert "预览PDF简历" in html
    assert "PDF：${c.has_pdf?'已保存':'未生成'}" in html
    assert "renderResumePreview" in html
    assert "工作经历" in html and "教育经历" in html
    assert "download=1" in html
    assert "新窗口打开PDF" in html
    assert "资质公示" in html and "存至本地" in html
    assert "generatePdf" in html
    assert "dedupeCandidates" in html



def test_pdf_contact_binary_fallback(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 phone 13800138000 email a@example.com")
    c = app.extract_contacts_from_pdf(pdf)
    assert c["phone"] == "13800138000"
    assert c["email"] == "a@example.com"
