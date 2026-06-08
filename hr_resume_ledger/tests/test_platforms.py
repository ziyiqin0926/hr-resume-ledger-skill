import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app


def test_platform_url_matching():
    assert app.platform_matches_url("zhaopin", "https://rd6.zhaopin.com/app/recommend?x=1")
    assert app.platform_matches_url("boss", "https://www.zhipin.com/web/geek/recommend")
    assert app.platform_matches_url("liepin", "https://lpt.liepin.com/resume/list")
    assert app.platform_matches_url("generic", "https://example.com/anything")


def test_candidate_link_matching_by_platform():
    assert app.looks_candidate_link({"href": "https://www.zhipin.com/web/geek/detail/1", "text": "李女士"}, "boss")
    assert app.looks_candidate_link({"href": "https://lpt.liepin.com/resume/detail/1", "text": "王先生"}, "liepin")
    assert app.looks_candidate_link({"href": "https://rd6.zhaopin.com/app/resume/1", "text": "吴女士"}, "zhaopin")


def test_unknown_platform_falls_back_to_generic():
    p = app.get_platform("unknown")
    assert p["id"] == "generic"


def test_platform_switcher_exists_in_frontend():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="platform"' in html
    assert 'value="zhaopin"' in html
    assert 'value="boss"' in html
    assert 'value="liepin"' in html
    assert '"platform":currentPlatform()' in html or "platform:currentPlatform()" in html
