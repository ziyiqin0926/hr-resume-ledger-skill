import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app


def test_match_score_percentage_for_recommendation_cards():
    rows = app.extract_recommendation_cards("""
吴女士
大专
导医
护士
内科
打电话
打招呼
苏先生
本科
导医
6千-1万
打电话
打招呼
李女士
高中
销售
打电话
打招呼
""", "本科 导医")
    report = app.build_match_report(rows, "本科 导医")
    assert report["total"] == 3
    assert report["matched"] == 2
    assert report["percent"] == 67
    assert report["items"][1]["name"] == "苏先生"
    assert report["items"][1]["matched"] is True
