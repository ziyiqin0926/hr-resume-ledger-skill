import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app


def test_extract_precise_basic_info_and_contacts():
    c = app.extract_candidate({"title": "王五-完整简历", "url": "u", "text": """
王五
男 28岁 本科 6年工作经验 在职-看看机会
手机：13800138000
邮箱：wangwu@example.com
微信：wx_wangwu88
现居住地：合肥 蜀山区
期望职位：导医
项目经历：负责导医分诊和客户接待
"""}, "导医 本科")
    assert c["age"] == "28"
    assert "6年" in c["age_years"]
    assert c["gender"] == "男"
    assert c["email"] == "wangwu@example.com"
    assert c["wechat"] == "wx_wangwu88"
    assert "合肥" in c["basic_info"]


def test_progress_state_can_be_updated_and_read():
    app.set_progress("x", total=3, current=1, message="正在打开详情", items=[{"name": "王五"}])
    p = app.get_progress("x")
    assert p["total"] == 3
    assert p["current"] == 1
    assert p["message"] == "正在打开详情"
    assert p["items"][0]["name"] == "王五"
