"""Generate a truthful Word report ONLY after live GPT API predictions were locked
and the separate scoring process has completed.

One report per independent blinded study, including all 100 telegrams and
both evidence conditions, per-code correspondence and real reference plaintext.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from docx import Document
from docx.shared import Cm,Pt,RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def para(doc,text,*,small=False):
    p=doc.add_paragraph()
    r=p.add_run(str(text))
    r.font.name="Microsoft JhengHei"
    r.font.size=Pt(8 if small else 9)
    return p

def add_table(doc,headers,rows):
    t=doc.add_table(rows=1,cols=len(headers))
    t.style="Table Grid"
    for i,x in enumerate(headers):
        cell=t.rows[0].cells[i];cell.text=str(x)
        for run in cell.paragraphs[0].runs:
            run.bold=True;run.font.size=Pt(8)
    header=OxmlElement("w:tblHeader")
    t.rows[0]._tr.get_or_add_trPr().append(header)
    for row in rows:
        cells=t.add_row().cells
        for i,item in enumerate(row):
            cells[i].text=str(item)
            for p in cells[i].paragraphs:
                for run in p.runs:run.font.size=Pt(7.5)
    return t

def build(study:str,public_dir:Path,private_dir:Path,result_dir:Path,out:Path):
    lockfile=result_dir/"predictions_LOCKED.json"
    locked=json.loads(lockfile.read_text(encoding="utf-8"))
    if locked.get("kind")!="ACTUAL_MULTI_ROUND_BLIND_EVALUATION" or locked.get("provider")!="OPENAI_RESPONSES":
        raise ValueError("Not a genuine GPT-6 Responses API run; Word benchmark report is forbidden")
    sealed=hashlib.sha256(lockfile.read_bytes()).hexdigest()
    evaluation=json.loads((result_dir/"evaluation.json").read_text(encoding="utf-8"))
    if evaluation["locked_sha256"]!=sealed:
        raise ValueError("Report cannot use tampered/unlocked inference results")
    case=json.loads((public_dir/(study+".json")).read_text(encoding="utf-8"))
    gold=json.loads((private_dir/(study+".gold.json")).read_text(encoding="utf-8"))
    if gold.get("public_sha256")!=next(x["public_sha256"] for x in locked["cases"] if x["study"]==study):
        raise ValueError("Mismatched reference corpus")
    runs={(x["n_messages"],x["condition"]):x for x in locked["cases"] if x["study"]==study}
    if len(runs)!=8 or set(runs)!={(n,c) for n in (10,25,50,100) for c in ("with_aux","without_aux")}:
        raise ValueError("Need all eight 10/25/50/100 x two-condition runs")
    metrics=[x for x in evaluation["results"] if x["study"]==study]
    assert len(metrics)==8
    doc=Document()
    sec=doc.sections[0];sec.top_margin=Cm(1.7);sec.bottom_margin=Cm(1.6)
    sec.left_margin=Cm(1.8);sec.right_margin=Cm(1.8)
    style=doc.styles["Normal"];style.font.name="Microsoft JhengHei";style.font.size=Pt(9)
    doc.add_heading("GPT-6 全自動跨報密碼研究｜真正盲測報告",0)
    para(doc,f"獨立碼本：{study}　模型：{locked['model']}　思考級別：{locked['reasoning_effort']}　回合：{locked['n_rounds']}")
    para(doc,"本文件只在真正 Responses API 呼叫、逐輪推論、鎖定猜測並揭盲評分後產生。"
         "合成電文並非真實歷史破譯成果；若沒有獨立錨點，無法保證碼組唯一可辨識。")
    para(doc,"鎖定 SHA256："+sealed,small=True)
    doc.add_heading("一、10／25／50／100 封 × 有無輔助資訊",1)
    add_table(doc,["電文數","情報","Top-1 碼組","Top-5 碼組","逐碼","完整電文","候選覆蓋"],[
        [m["n_messages"],"有" if m["metadata"] else "無",
         f"{m['correct_types']}/{m['code_types']}（{m['type_top1']:.1%}）",
         f"{m['top5_correct_types']}/{m['code_types']}（{m['type_top5']:.1%}）",
         f"{m['correct_positions']}/{m['positions']}（{m['position_accuracy']:.1%}）",
         f"{m['complete_messages']}/{m['n_messages']}",
         f"{m['lexicon_coverage']:.1%}"]
        for m in sorted(metrics,key=lambda r:(r["n_messages"],not r["metadata"]))])
    doc.add_heading("二、逐輪正確率（包含詞庫擴充後與碼組重排後）",1)
    trace=[x for x in evaluation["round_trajectories"] if x["study"]==study]
    add_table(doc,["封數","情報","輪","階段","碼組命中","逐碼命中","整封"],[
        [r["n_messages"],r["condition"],r["round"],r["stage"],
         f"{r['correct_types']}/{r['code_types']}",
         f"{r['correct_positions']}/{r['positions']}",
         str(r["complete_messages"])]
        for r in trace])
    doc.add_page_break()
    doc.add_heading("附錄 A：100 封原始密電／最終還原／正確明文",1)
    para(doc,"此附錄使用 100 封條件下兩次獨立完整 Agent 執行結果。每個碼組均逐一與保密答案對位；"
         "✓ 代表完全吻合；✗ 代表錯誤或未解。")
    yes=runs[(100,"with_aux")]["mapping"]
    no=runs[(100,"without_aux")]["mapping"]
    key=gold["code_to_word"]
    for i,m in enumerate(case["messages"],1):
        codes=m["codes"]
        original=gold["plaintext_segments"][i-1]["segments"]
        assert m["id"]==gold["plaintext_segments"][i-1]["id"] and len(codes)==len(original)
        pos=[(c,yes[c],no[c],key[c]) for c in codes]
        hits=sum(w==key[c] for c,w,_,_ in pos)
        doc.add_heading(f"{i:03d}　{m['id']}　有情報正確 {hits}/{len(codes)}",2)
        para(doc,f"收件時間：{m['received_at']}　發：{m['sender']}　收：{m['recipient']}",small=True)
        if m.get("observations"):
            for o in m["observations"]:
                para(doc,f"第三方情報：{o['observed_at']}／{o['source']}／{o['activity']}／"
                     f"{o.get('destination','')}／可信度 {o['confidence']}／{o['status']}",small=True)
        else:
            para(doc,"第三方情報：此封沒有額外觀察。",small=True)
        para(doc,"原始密電："+" ".join(codes))
        para(doc,"有情報最終還原："+"｜".join(yes[c] for c in codes))
        para(doc,"無情報最終還原："+"｜".join(no[c] for c in codes))
        para(doc,"正確明文："+"｜".join(original))
        add_table(doc,["碼組","有情報猜測","無情報猜測","正確明文","有情報","無情報"],[
            [c,w,z,key[c],"✓" if w==key[c] else "✗","✓" if z==key[c] else "✗"]
            for c,w,z,_ in pos])
        if i%2==0 and i!=100:doc.add_page_break()
    out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists():raise FileExistsError("Will not overwrite existing released Word report")
    doc.save(out)
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study",required=True)
    p.add_argument("--public-dir",type=Path,required=True)
    p.add_argument("--private-dir",type=Path,required=True)
    p.add_argument("--results-dir",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    print(build(a.study,a.public_dir,a.private_dir,a.results_dir,a.out))

if __name__=="__main__":main()
