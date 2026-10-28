"""Synchronize the Vercel Mock workbench with the canonical Python GUI.

Usage:
    python scripts/sync_vercel_workbench.py --write
    python scripts/sync_vercel_workbench.py --check

The local GUI is the single visual/interaction source of truth. Vercel injects
the browser-only mock API ahead of the same extracted workbench JavaScript.
No production backend routes, model URLs, or personal cases are copied.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "src/han_codebook/static/index.html"
DEMO_HTML = ROOT / "vercel-demo/index.html"
DEMO_JS = ROOT / "vercel-demo/workbench.js"

LOCAL_CAPTION = "本機瀏覽器介面 · 歷史虛構案例 · 未驗證候選絕不等於真實破譯"
DEMO_CAPTION = (
    "公開 MOCK LLM 展示版 · 與本機相同的研究工作台介面 · "
    "全部為公開合成資料、絕不呼叫真實模型"
)
TOP_BAR = '<div class="panel"><div class="row"><div><label for="caseList">'
MOCK_BANNER = (
    '<div class="panel"><p class="alert" role="status">'
    '【公開 Mock 展示】這裡與本機研究版共用相同的 GUI 及操作流程；'
    '計算、LLM 候選、時序分析與報告由純瀏覽器合成資料模擬。'
    '沒有連接真實模型、沒有歷史破譯結論，也不會把輸入資料送出網頁。'
    '編輯與另存只在目前頁面有效，重新整理即消失。'
    '</p><div class="row"><div><label for="caseList">'
)
SCRIPTS = (
    '<script src="/mock_api.js" defer></script>\n'
    '<script src="/workbench.js" defer></script>'
)


def generate() -> tuple[str, str]:
    source = CANONICAL.read_text(encoding="utf-8")
    matches = list(re.finditer(r"<script>([\s\S]*?)</script>", source, re.I))
    if len(matches) != 1 or source.count(LOCAL_CAPTION) != 1 or source.count(TOP_BAR) != 1:
        raise ValueError("Canonical GUI structure changed; review synchronization rules")
    match = matches[0]
    js = match.group(1).strip() + "\n"
    html = (
        source[:match.start()] + SCRIPTS + source[match.end():]
    ).replace(LOCAL_CAPTION, DEMO_CAPTION).replace(TOP_BAR, MOCK_BANNER)
    return html, js


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    html, js = generate()
    if args.write:
        DEMO_HTML.write_text(html, encoding="utf-8")
        DEMO_JS.write_text(js, encoding="utf-8")
        print("Updated Vercel Mock GUI from canonical local workbench")
        return 0
    mismatched = [
        str(path.relative_to(ROOT))
        for path, content in ((DEMO_HTML, html), (DEMO_JS, js))
        if path.read_text(encoding="utf-8") != content
    ]
    if mismatched:
        print("GUI parity check failed: " + ", ".join(mismatched), file=sys.stderr)
        print("Run python scripts/sync_vercel_workbench.py --write", file=sys.stderr)
        return 1
    print("Vercel / local GUI parity: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
