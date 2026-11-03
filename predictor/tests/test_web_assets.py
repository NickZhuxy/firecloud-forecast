"""The static map page stays plain and loads nothing from other hosts."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"
FILES = ("index.html", "style.css", "firecloud.js")


def test_web_assets_are_plain_and_self_contained():
    texts = {}
    for name in FILES:
        path = WEB / name
        assert path.is_file(), name
        texts[name] = path.read_text(encoding="utf-8")
        assert "http://" not in texts[name] and "https://" not in texts[name], name

    css = texts["style.css"]
    for banned in ("box-shadow", "gradient", "transition", "animation", "backdrop-filter"):
        assert banned not in css, banned
    radii = re.findall(r"border-radius\s*:\s*([^;}]+)", css)
    assert radii and all(value.strip() == "0" for value in radii)
    assert re.search(r"\*\s*\{[^}]*border-radius\s*:\s*0", css)

    html = texts["index.html"]
    referenced = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', html)
    assert sorted(referenced) == ["firecloud.js", "style.css"]
