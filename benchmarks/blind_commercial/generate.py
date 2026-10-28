"""Generate never-before-published blind phrase-codebook experiments.

The LLM sees ONLY the public_case.json. Secret code/phrase assignments are
stored outside the repository. No fixed code position maps to a semantic role.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import secrets
from datetime import date, timedelta
from pathlib import Path

GENERATOR_VERSION = "blind-phrase-v1"
# These are generator-only phrases, not evaluation hints passed to the LLM.
UNITS = ["後勤司令部", "第二補給處", "前線觀察站", "工兵連", "軍司令部", "通信隊",
         "軍醫所", "運輸中隊", "第一營", "第二營", "情報分隊", "彈藥庫"]
PLACES = ["北線", "南側道路", "河口", "山腳", "西側公路", "東部橋梁", "補給倉庫",
          "前線基地", "臨時集結點", "第二營駐地", "渡口", "山區道路"]
OBJECTS = ["車隊", "糧秣", "燃料", "藥品", "彈藥", "傷員", "野戰電台", "工兵設備",
           "醫療器材", "補給物資", "偵察報告", "運輸車輛"]
TIMES = ["今夜", "明晨", "午前", "傍晚", "兩日內", "近日", "凌晨", "本週",
         "目前", "午後", "次日", "昨日"]
STATUSES = ["受阻", "安全通行", "需要修復", "尚未到達", "已完成", "正在整備",
            "等待確認", "繼續前進", "暫時中止", "仍需補充", "未見異常", "已抵達"]
WORDS = ["奉令", "請", "於", "經", "已", "仍", "由", "前往", "附近", "轉送",
         "回電", "報告", "準備", "確認", "預計", "完成", "調整", "改走", "等待",
         "出發", "抵達", "注意", "警戒", "聯絡", "供應", "不足", "暫停", "補給",
         "觀察", "接應", "前線", "軍部", "道路", "橋梁", "恢復", "清點", "通知",
         "依原計畫", "繼續", "要求", "查明", "運抵", "立即", "預先", "通知各單位"]
COMMON = ["報告", "請", "注意", "於", "今夜", "車隊", "補給", "道路", "確認",
          "前線", "運抵", "仍", "等待", "已"]
UNITS_LIST = [UNITS, PLACES, OBJECTS, TIMES, STATUSES, WORDS]

# Human-written, variable-length phrase snippets. Actual messages combine
# independent snippets in changing order with optional clauses and omissions.
TEMPLATES = (
    ("奉令", "於", "{time}", "{unit}", "前往", "{place}", "請", "回電"),
    ("{unit}", "報告", "{object}", "已", "抵達", "{place}"),
    ("{place}", "附近", "道路", "{status}", "請", "注意"),
    ("預計", "{time}", "經", "{place}", "轉送", "{object}"),
    ("{unit}", "等待", "{object}", "確認", "{status}"),
    ("{object}", "仍", "不足", "{unit}", "要求", "補給"),
    ("請", "{unit}", "聯絡", "{place}", "查明", "{status}"),
    ("{place}", "橋梁", "{status}", "仍", "等待", "恢復"),
    ("昨日", "{unit}", "已", "清點", "{object}", "請", "確認"),
    ("{time}", "{unit}", "預先", "準備", "{object}"),
    ("{unit}", "通知各單位", "{place}", "需", "警戒"),
    ("{place}", "觀察", "{object}", "仍", "未見異常"),
    ("{unit}", "改走", "{place}", "接應", "{object}"),
    ("{object}", "由", "{unit}", "轉送", "{place}"),
    ("{unit}", "已", "完成", "道路", "清點"),
    ("{unit}", "報告", "{place}", "正在整備"),
    ("前線", "{unit}", "要求", "{object}", "立即", "運抵"),
    ("{unit}", "等待", "{place}", "確認", "請", "回電"),
    ("{object}", "{status}", "通知", "{unit}"),
    ("{time}", "{place}", "觀察", "仍", "未見異常"),
)
# Include generator-only words used in templates.
SPECIAL = ["需"]
VOCAB = sorted({*UNITS, *PLACES, *OBJECTS, *TIMES, *STATUSES, *WORDS,
                *SPECIAL, *(t for tpl in TEMPLATES for t in tpl if not t.startswith("{"))})


def digest(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def make_one(index: int, rng: random.Random, codebook: dict[str, str]) -> tuple[dict, list[str]]:
    unit, place, obj, time, status = (rng.choice(src) for src in
                                     (UNITS, PLACES, OBJECTS, TIMES, STATUSES))
    context = {"unit": unit, "place": place, "object": obj,
               "time": time, "status": status}
    blocks = [rng.choice(TEMPLATES) for _ in range(rng.choice((1, 2, 2, 3)))]
    if rng.random() < .5:
        rng.shuffle(blocks)
    text = []
    for block in blocks:
        expanded = [context.get(token[1:-1], token)
                    if token.startswith("{") else token for token in block]
        # Ellipsis and optional words produce unequal message lengths.
        if len(expanded) > 5 and rng.random() < .3:
            expanded.pop(rng.randrange(1, len(expanded)-1))
        text.extend(expanded)
    when = date(1942, 5, 1) + timedelta(days=index // rng.choice((2, 3, 4)))
    sender = unit if rng.random() < .45 else rng.choice(UNITS)
    recipient = rng.choice([u for u in UNITS if u != sender])
    notes = []
    if rng.random() < .65:
        # Separate observation channel: some relevant, others noisy or
        # deliberately different. Relevance labels are NEVER public.
        related = rng.random() < .58
        observed_object = obj if related else rng.choice(OBJECTS)
        observed_place = place if related else rng.choice(PLACES)
        notes.append({"source": "第三方交通或物資觀察（合成）",
                      "observed_at": (when + timedelta(days=rng.choice((-2,-1,0,1,2)))).isoformat(),
                      "activity": rng.choice(("見到", "傳聞", "疑似發現")) + observed_object + "活動",
                      "destination": observed_place,
                      "confidence": round(rng.uniform(.2, .75),2),
                      "status": "關聯未證實"})
    if rng.random() < .20:
        notes.append({"source": "未核實地方報告（合成）",
                      "observed_at": when.isoformat(),
                      "activity": rng.choice(("補給活動", "人員往來", "車輛移動")),
                      "destination": rng.choice(PLACES),
                      "confidence": .2, "status": "可能與密電無關"})
    return ({"id": f"BLIND-{index+1:03d}",
             "codes": [codebook[word] for word in text],
             "sender": sender, "recipient": recipient,
             "received_at": when.isoformat(),
             "observations": notes}, text)


def generate(public_dir: Path, private_dir: Path, *, repeats: int = 3,
             fixture_seed: int | None = None) -> list[dict]:
    root=Path(__file__).resolve().parents[2]
    public_dir,private_dir=public_dir.resolve(),private_dir.resolve()
    if public_dir==private_dir or public_dir in private_dir.parents or private_dir in public_dir.parents:
        raise ValueError("Public and private output directories must be separate")
    if private_dir==root or root in private_dir.parents:
        raise ValueError("Secret reference must be outside the Git working tree")
    public_dir.mkdir(parents=True,exist_ok=True)
    private_dir.mkdir(parents=True,exist_ok=True)
    manifests=[]
    for i in range(repeats):
        study=f"blind_{i+1:02d}"
        rng = random.Random(fixture_seed+i) if fixture_seed is not None else random.Random(secrets.randbits(128))
        code_rng = random.Random(fixture_seed+10000+i) if fixture_seed is not None else secrets.SystemRandom()
        codes=code_rng.sample(range(1000,9999),len(VOCAB))
        codebook=dict(zip(VOCAB,[str(n) for n in codes]))
        msgs,plaintext=[],[]
        for j in range(100):
            m,words=make_one(j,rng,codebook)
            msgs.append(m);plaintext.append({"id":m["id"],"segments":words})
        # Absolute sequence number, not a sentence-field/slot index.
        public={"kind":"BLIND_UNSTRUCTURED_CODEBOOK_V1",
                "case_id":study,
                "description":"Synthetic unstructured Chinese phrase-codebook intercepts; metadata and noisy observations, no known plaintext",
                "profiles":{"neutral":{"keywords":["軍事通信","運輸","活動","時間"],
                            "lexicon":{w:1.0 for w in COMMON},"sentences":[]}},
                "messages":msgs,"known_pairs":[],"candidate_ideas":{}}
        reference={"case_id":study,"code_to_word":{code:word for word,code in codebook.items()},
                   "plaintext_segments":plaintext,
                   "public_sha256":digest(public),"fixture_only":fixture_seed is not None}
        pub=public_dir/f"{study}.json"
        secret=private_dir/f"{study}.gold.json"
        if pub.exists() or secret.exists():
            raise FileExistsError(f"Refusing to overwrite a prior blinded run: {study}")
        pub.write_text(json.dumps(public,indent=2,ensure_ascii=False),encoding="utf-8")
        with secret.open("x",encoding="utf-8") as f:
            json.dump(reference,f,indent=2,ensure_ascii=False)
        try:os.chmod(secret,0o600)
        except OSError:pass
        manifests.append({"case_id":study,"public_file":pub.name,
                          "public_sha256":digest(public),
                          "n_messages":len(msgs),"n_code_types":len(VOCAB),
                          "fixture_only":fixture_seed is not None})
    (public_dir/"manifest.json").write_text(json.dumps(
         {"protocol":GENERATOR_VERSION,"sizes":[10,25,50,100],
          "studies":manifests,"gold_location":"OFF-REPO PRIVATE; do not upload"},
         indent=2,ensure_ascii=False),encoding="utf-8")
    return manifests


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--public-dir",type=Path,required=True)
    p.add_argument("--private-dir",type=Path,required=True)
    p.add_argument("--repeats",type=int,default=3)
    p.add_argument("--fixture-seed",type=int,help="INSECURE: only for no-network unit tests")
    args=p.parse_args()
    if not 1<=args.repeats<=12: p.error("--repeats must be 1..12")
    print(json.dumps(generate(args.public_dir,args.private_dir,
                              repeats=args.repeats,fixture_seed=args.fixture_seed),
                     indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()
