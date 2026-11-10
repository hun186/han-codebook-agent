"""Readable Word export of a completed, explicitly unverified research analysis.

No secrets, API prompts or hidden synthetic ground truth are included.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt


def _table(doc: Document, headings: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(headings))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, title in enumerate(headings):
        cell = table.rows[0].cells[i]
        cell.text = title
        for run in cell.paragraphs[0].runs:
            run.bold = True
    for values in rows:
        cells = table.add_row().cells
        for i, value in enumerate(values):
            cells[i].text = str(value)
    doc.add_paragraph()


def investigation_docx(result: dict[str, Any], events: list[dict[str, Any]]) -> bytes:
    """Return a DOCX payload; original verified mappings are never replaced."""
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.7)
    section.right_margin = Inches(0.7)
    styles = doc.styles
    styles["Normal"].font.name = "Microsoft JhengHei"
    styles["Normal"].font.size = Pt(9)
    for key in ("Title", "Heading 1", "Heading 2"):
        styles[key].font.name = "Microsoft JhengHei"

    title = doc.add_heading("中文歷史詞組密電｜研究分析報告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("注意：尚未驗證的模型與人工假說，不等於密電破解成果。")
    proposals = result.get("proposals", {})
    verified = sum(p.get("status") == "verified_alignment" for p in proposals.values())
    _table(doc, ["項目", "內容"], [
        ["案例", str(result.get("case_id", ""))],
        ["分析電文", str(len(result.get("decoded_messages", [])))],
        ["已驗證碼組", str(verified)],
        ["待驗證碼組", str(len(proposals) - verified)],
        ["完成 LLM 回合", str(result.get("agent_rounds_completed", 0))],
        ["使用元數據", str(result.get("metadata_used", False))],
    ])
    metrics = result.get("llm_api_metrics")
    if isinstance(metrics, dict):
        n = metrics.get("attempts", 0)
        rate = metrics.get("json_completeness_rate")
        doc.add_heading("LLM API JSON 完整性與 Token 用量（非破解正確率）", level=1)
        _table(doc, ["項目", "結果"], [
            ["API 請求／JSON 有效", f"{n}／{metrics.get('json_complete_attempts',0)}"],
            ["JSON 完整率", f"{rate*100:.1f}%" if rate is not None else "未量測"],
            ["截斷／增額重試", f"{metrics.get('finish_reason_length_count',0)}／{metrics.get('retries',0)}"],
            ["有回報 Token 用量", f"{metrics.get('usage_reported_attempts',0)}／{n}"],
            ["回報輸入／輸出／總 Token",
             f"{metrics.get('prompt_tokens_reported',0)}／"
             f"{metrics.get('completion_tokens_reported',0)}／"
             f"{metrics.get('total_tokens_reported',0)}"],
            ["快取輸入 Tokens／有快取回報請求",
             f"{metrics.get('cached_prompt_tokens_reported',0)}／"
             f"{metrics.get('cache_reported_attempts',0)}／{n}"],
            ["快取命中率（僅已回報部分）",
             f"{metrics['cache_hit_rate']*100:.1f}%" if metrics.get("cache_hit_rate") is not None
             else "未回報"],
        ])
        doc.add_paragraph("快取僅重用輸入前綴，不重用模型答案。未回報快取資訊不代表零命中；"
                          "沒有可靠單價時不推算節省金額。")
        doc.add_paragraph("完整率只反映 API JSON 結構完整，並非密文破解正確率。"
                          "Token 用量缺漏不能視為零消耗；重試同樣可能計費。")
    coverage = result.get("code_llm_coverage")
    if isinstance(coverage, dict):
        doc.add_heading("LLM 碼組請求涵蓋（不是破解正確率）", level=1)
        _table(doc, ["項目", "數量"], [
            ["未驗證碼組", str(coverage["unverified_code_count"])],
            ["至少曾被送交 LLM 的不同碼組",
             str(coverage["queried_distinct_code_count"])],
            ["從未作為 LLM 目標的碼組",
             str(coverage["not_queried_code_count"])],
            ["每回合直接請求上限", str(coverage["per_round_target_cap"])],
        ])
        doc.add_paragraph(
            "未被直接請求的碼組仍可能有統計候選；曾被請求不代表模型"
            "正確解讀或取得可信明文。每回合的抽樣電文不是全部原始語料。"
        )
    quality = result.get("hypothesis_quality")
    if isinstance(quality, dict) and quality.get("presentation_abstained_code_count", 0) > 0:
        doc.add_heading("推論不確定性（不是破解正確率）", level=1)
        doc.add_paragraph(
            "部分碼組候選近似同分，或過多不同碼組被配成同一詞組。"
            "為避免誤認已破解，逐封電文閱讀欄以「[碼組:待判]」標記這些位置，"
            "但下方碼組候選表仍完整保留原始 Top-1 假說供研究。"
        )
        doc.add_paragraph(
            f"待判碼組：{quality.get('presentation_abstained_code_count')}；"
            f"近似同分：{quality.get('near_tied_unverified_code_count')}；"
            f"最大重複詞組涵蓋：{quality.get('dominant_unverified_term_code_count')} 個碼組。"
        )
    baseline = next((e.get("payload", {}).get("mapping", {}) for e in events if e.get("stage") == "statistical_baseline"), {})
    scores = next((e.get("payload", {}).get("score", "") for e in events if e.get("stage") == "statistical_baseline"), "")
    round_rows = [["Round 0 (統計基線)", "—", "—", "—", str(scores)]]
    suggested = {x.get("round"): x.get("payload", {}) for x in events if x.get("stage") == "llm_proposals_unverified"}
    for e in events:
        if e.get("stage") != "rescore":
            continue
        payload = e.get("payload", {})
        sent = suggested.get(e.get("round"), {})
        round_rows.append([str(e.get("round", "")), str(len(sent.get("accepted", []))),
                           str(sent.get("rejected_count", 0)), str(payload.get("changed_count", "")),
                           str(payload.get("score", ""))])
    doc.add_heading("一、逐輪分析", level=1)
    _table(doc, ["回合", "採納假說", "拒絕", "首選變更", "內部目標分數"], round_rows)
    doc.add_paragraph("內部目標分數不能視為機率或正確率；不同設定間亦不適合直接比較。")
    doc.add_heading("二、碼組候選與已知明文", level=1)
    _table(doc, ["碼組", "驗證狀態", "統計初選", "最終候選", "是否變動"], [
        [code, "已驗證明文" if p.get("status") == "verified_alignment" else "未驗證假說",
         str(baseline.get(code, "")), str(p.get("term", "")),
         "是" if baseline.get(code) != p.get("term") else "否"]
        for code, p in sorted(proposals.items())
    ])
    overrides = result.get("bold_hypotheses", {})
    if overrides:
        doc.add_heading("三、研究員大膽指定（反事實假說）", level=1)
        doc.add_paragraph("以下為研究員自行提出的反對假說，不會覆寫可信明密文證據，也未作為本次求解器的 verified anchor。")
        _table(doc, ["碼組", "已驗證原詞", "研究員替代假說", "理由"], [
            [code, str(result.get("verified_anchors", {}).get(code, "")), str(item.get("term", "")),
             str(item.get("note", ""))]
            for code, item in sorted(overrides.items())
        ])
    doc.add_heading("四、逐封電文候選解讀", level=1)
    _table(doc, ["電文", "推測領域", "目前候選明文", "已驗證碼組"], [
        [str(m.get("id", "")), str(m.get("domain_inferred") or "未知"), str(m.get("cautious_reading", m.get("reading", ""))),
         f"{m.get('verified_codes',0)}/{m.get('total_codes',0)}"]
        for m in result.get("decoded_messages", [])
    ])
    doc.add_heading("五、研究限制", level=1)
    for line in (
        "僅處理固定分隔數字碼組，不代表可破解所有真實電碼系統。",
        "詞彙先驗、收發者和目擊情資都是不確定的推理條件。",
        "模型候選與研究員大膽指定均非已驗證明文；不能改寫可靠原始紀錄。",
        "應以推理過程完全隔離的獨立標準答案，才能評估真實正確率。",
    ):
        doc.add_paragraph(line, style="List Bullet")
    out = BytesIO()
    doc.save(out)
    return out.getvalue()
