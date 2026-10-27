"""Evidence-constrained research prototype for historical Chinese phrase-codebooks.

Not a general decryption engine. In particular it does not remove additive superencipherment.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
import json
import math
import random


class CaseError(ValueError):
    pass


def load_case(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        case = json.load(f)
    validate_case(case)
    return case


def validate_case(case: dict[str, Any]) -> None:
    if not isinstance(case.get("messages"), list) or not case["messages"]:
        raise CaseError("messages must be a non-empty array")
    ids = set()
    for m in case["messages"]:
        if not isinstance(m.get("id"), str) or m["id"] in ids:
            raise CaseError("each message must have a unique string id")
        ids.add(m["id"])
        if not isinstance(m.get("codes"), list) or not m["codes"] or not all(isinstance(x, str) and x.isdigit() for x in m["codes"]):
            raise CaseError(f"message {m['id']}: codes must be a non-empty array of digit strings")
    if not isinstance(case.get("profiles"), dict) or not case["profiles"]:
        raise CaseError("profiles must be a non-empty object")
    for domain, profile in case["profiles"].items():
        if not isinstance(profile.get("lexicon", {}), dict):
            raise CaseError(f"profile {domain} lexicon must be an object")
        if not isinstance(profile.get("sentences", []), list):
            raise CaseError(f"profile {domain} sentences must be an array")
        for sentence in profile.get("sentences", []):
            if not isinstance(sentence, list) or not all(isinstance(s, str) and s for s in sentence):
                raise CaseError(f"profile {domain} sentence must be array of nonempty words")
    for m in case["messages"]:
        obs = m.get("observations", [])
        if not isinstance(obs, list):
            raise CaseError(f"message {m['id']}: observations must be a list")
        for o in obs:
            if not isinstance(o, dict) or not isinstance(o.get("source"), str) or not o["source"].strip():
                raise CaseError(f"message {m['id']}: observation must have a source")
            if not isinstance(o.get("note", ""), str):
                raise CaseError(f"message {m['id']}: observation note must be text")
            confidence = o.get("confidence", 0.5)
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise CaseError(f"message {m['id']}: observation confidence must be 0..1")
    for pair in case.get("known_pairs", []):
        m_id = pair.get("message_id")
        if m_id not in ids:
            raise CaseError(f"known pair references unknown message {m_id}")
        if "segments" in pair:
            segments = pair["segments"]
            if not isinstance(segments, list) or not all(isinstance(s, str) and s for s in segments):
                raise CaseError("segments must be nonempty strings")
            if pair.get("plaintext") is not None and "".join(segments) != pair["plaintext"]:
                raise CaseError(f"known pair {m_id}: segments do not concatenate to plaintext")


def domain_for_message(message: dict[str, Any], profiles: dict[str, Any], use_metadata: bool) -> str | None:
    if not use_metadata:
        return None
    if message.get("domain") in profiles:
        return message["domain"]
    text = " ".join(str(message.get(k, "")) for k in ("sender", "recipient", "notes", "unit"))
    observations = message.get("observations", [])
    # Third-party sightings are uncertain context, not verified plaintext.
    observation_texts = [(" ".join(str(o.get(key, "")) for key in ("note", "destination", "status", "activity")),
                          float(o.get("confidence", 0.5))) for o in observations]
    points = {
        name: sum(len(keyword) for keyword in profile.get("keywords", []) if keyword in text)
        + 0.6 * sum(len(keyword) * confidence for note, confidence in observation_texts
                    for keyword in profile.get("keywords", []) if keyword in note)
        for name, profile in profiles.items()
    }
    best = max(points.values(), default=0)
    winners = [k for k, v in points.items() if v == best and v > 0]
    return winners[0] if len(winners) == 1 else None


def segmentation_candidates(plaintext: str, n_codes: int, vocabulary: set[str], max_paths: int = 8) -> list[list[str]]:
    """Dictionary guided segmentation for review only; never promotes ambiguous output to verified."""
    from functools import lru_cache
    if len(plaintext) > 500:
        raise CaseError("unsegmented known plaintext over 500 characters requires explicit segments")
    @lru_cache(None)
    def solve(pos: int, slots: int) -> tuple[tuple[float, tuple[str, ...]], ...]:
        if slots == 0:
            return ((0.0, ()),) if pos == len(plaintext) else ()
        if len(plaintext) - pos < slots:
            return ()
        found = []
        for end in range(pos + 1, len(plaintext) - slots + 2):
            segment = plaintext[pos:end]
            # Known multi-character phrases rank above unknown pieces; single characters remain possible.
            value = (3.0 + 0.25 * len(segment)) if segment in vocabulary else (0.0 if len(segment) == 1 else -2.5 * len(segment))
            for rest_score, rest in solve(end, slots - 1):
                found.append((rest_score + value, (segment,) + rest))
        return tuple(sorted(found, key=lambda x: (-x[0], x[1]))[:max_paths])
    return [list(terms) for _, terms in solve(0, n_codes)]


def anchors_and_review(case: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]], set[str]]:
    by_id = {m["id"]: m for m in case["messages"]}
    vocabulary = {w for p in case["profiles"].values() for w in p.get("lexicon", {})}
    vocabulary.update(w for p in case["profiles"].values() for line in p.get("sentences", []) for w in line)
    anchors: dict[str, str] = {}
    reviews: list[dict[str, Any]] = []
    # Stage all constraints: conflicting evidence is fatal rather than letting a dictionary overwrite it.
    for pair in case.get("known_pairs", []):
        m = by_id[pair["message_id"]]
        codes = m["codes"]
        segments = pair.get("segments")
        if segments is None:
            if not isinstance(pair.get("plaintext"), str):
                raise CaseError(f"known pair {m['id']} must have plaintext or segments")
            suggestions = segmentation_candidates(pair["plaintext"], len(codes), vocabulary)
            reviews.append({"message_id": m["id"], "status": "manual_segmentation_required", "suggestions": suggestions})
            continue
        if len(segments) != len(codes):
            raise CaseError(f"known pair {m['id']}: segment count must match code count")
        seen_in_pair: dict[str, str] = {}
        for code, term in zip(codes, segments):
            if code in seen_in_pair and seen_in_pair[code] != term:
                raise CaseError(f"known pair {m['id']}: contradictory repeated code {code}")
            seen_in_pair[code] = term
            if code in anchors and anchors[code] != term:
                raise CaseError(f"contradictory known plaintext for code {code}: {anchors[code]} vs {term}")
            anchors[code] = term
        vocabulary.update(segments)
    return anchors, reviews, vocabulary


@dataclass
class LanguageModel:
    unigrams: Counter[str]
    bigrams: Counter[tuple[str, str]]
    vocabulary: set[str]
    # priors supplied as lexicon weights, not measured frequencies
    prior: dict[str, float]

    def unigram(self, word: str) -> float:
        total = sum(self.unigrams.values()) + sum(self.prior.values()) + 0.2 * len(self.vocabulary)
        count = self.unigrams[word] + self.prior.get(word, 0) + 0.2
        return math.log(count / max(total, 1))

    def transition(self, previous: str, word: str) -> float:
        n = sum(p for (a, _), p in self.bigrams.items() if a == previous)
        # A mild additive smoothing over the union vocabulary.
        value = self.bigrams[(previous, word)] + 0.3
        return math.log(value / (n + 0.3 * (len(self.vocabulary) + 2)))


def build_models(case: dict[str, Any], anchors: dict[str, str]) -> dict[str | None, LanguageModel]:
    profiles = case["profiles"]
    vocab = {w for p in profiles.values() for w in p.get("lexicon", {})}
    vocab.update(w for p in profiles.values() for line in p.get("sentences", []) for w in line)
    vocab.update(anchors.values())
    models = {}
    for domain in [None, *profiles.keys()]:
        unigram = Counter()
        bigram = Counter()
        prior = defaultdict(float)
        relevant = profiles.values() if domain is None else [profiles[domain]]
        for p in relevant:
            for term, wt in p.get("lexicon", {}).items():
                prior[term] += max(0.0, float(wt))
            for line in p.get("sentences", []):
                seq = ["<S>", *line, "</S>"]
                unigram.update(seq)
                bigram.update(zip(seq, seq[1:]))
        models[domain] = LanguageModel(unigram, bigram, vocab, dict(prior))
    return models


def analyze(case: dict[str, Any], use_metadata: bool = True, llm_hints: dict[str, dict[str, float]] | None = None,
            iterations: int = 8, restarts: int = 4, seed: int = 7) -> dict[str, Any]:
    """Local coordinate-ascent codebook hypotheses, with immutable verified anchors."""
    validate_case(case)
    anchors, reviews, vocab = anchors_and_review(case)
    if not vocab:
        raise CaseError("empty vocabulary; provide profile lexicon or sample sentences")
    messages = case["messages"]
    models = build_models(case, anchors)
    tagged = [(m, domain_for_message(m, case["profiles"], use_metadata)) for m in messages]
    all_codes = sorted({code for m in messages for code in m["codes"]})
    unknown_codes = [code for code in all_codes if code not in anchors]
    freq = Counter(code for m in messages for code in m["codes"])
    unknown_codes.sort(key=lambda c: (-freq[c], c))
    choices = sorted(vocab)
    hints = llm_hints or {}

    # Cache vocabulary probabilities. The same domain/word pairs are queried
    # repeatedly during coordinate search, particularly for 100+ telegrams.
    @lru_cache(maxsize=None)
    def unigram(domain: str | None, word: str) -> float:
        return models[domain].unigram(word)

    @lru_cache(maxsize=None)
    def transition(domain: str | None, previous: str, word: str) -> float:
        return models[domain].transition(previous, word)

    # An assignment change only affects messages containing the target code.
    # Preserve all adjacent transitions, including code -> same code edges.
    occurrences: dict[str, list[tuple[str | None, str, str]]] = defaultdict(list)
    for message, domain in tagged:
        codes = message["codes"]
        for pos, code in enumerate(codes):
            prev = codes[pos - 1] if pos else "<S>"
            nxt = codes[pos + 1] if pos + 1 < len(codes) else "</S>"
            occurrences[code].append((domain, prev, nxt))

    def change_delta(code: str, candidate: str, assignment: dict[str, str], *,
                     distinct_counts: Counter[str] | None = None) -> float:
        """Exact change in local lexical and transition terms, without rescoring every message."""
        previous_word = assignment[code]
        if previous_word == candidate:
            return 0.0
        delta = 0.0
        for domain, previous_code, next_code in occurrences[code]:
            old_left = previous_word if previous_code == code else ("<S>" if previous_code == "<S>" else assignment[previous_code])
            new_left = candidate if previous_code == code else old_left
            old_right = previous_word if next_code == code else ("</S>" if next_code == "</S>" else assignment[next_code])
            new_right = candidate if next_code == code else old_right
            delta += 0.55 * (unigram(domain, candidate) - unigram(domain, previous_word))
            delta += 1.7 * (transition(domain, new_left, candidate) - transition(domain, old_left, previous_word))
            # A repeated code immediately following itself is handled by the outgoing
            # edge once; otherwise the next node's incoming edge is counted here.
            if next_code != code:
                multiplier = 0.9 if next_code == "</S>" else 1.7
                delta += multiplier * (transition(domain, candidate, new_right) - transition(domain, previous_word, old_right))
            delta += min(0.6, max(0.0, hints.get(code, {}).get(candidate, 0.0))) - min(0.6, max(0.0, hints.get(code, {}).get(previous_word, 0.0)))
        if distinct and distinct_counts is not None:
            a, b = distinct_counts[previous_word], distinct_counts[candidate]
            # Distinct penalty is -7 for every repeated code->term mapping.
            delta += 7.0 * (int(a >= 2) - int(b >= 1))
        return delta

    distinct = bool(case.get("codebook_assumptions", {}).get("distinct_phrases", False))
    def score(assignment: dict[str, str]) -> float:
        out = 0.0
        for m, domain in tagged:
            last = "<S>"
            for code in m["codes"]:
                word = assignment[code]
                out += 0.55 * unigram(domain, word)
                out += 1.7 * transition(domain, last, word)
                out += min(0.6, max(0.0, hints.get(code, {}).get(word, 0.0)))
                last = word
            out += 0.9 * transition(domain, last, "</S>")
        if distinct:
            counts = Counter(assignment.values())
            out -= 7.0 * sum(v - 1 for v in counts.values() if v > 1)
        return out

    rng = random.Random(seed)
    best_assign = anchors.copy()
    best_score = float("-inf")
    if not unknown_codes:
        best_score = score(best_assign)
    for start in range(restarts):
        assignment = anchors.copy()
        for code in unknown_codes:
            # Good initializations with occasional non-greedy starts for escaping local maxima.
            candidates = sorted(choices, key=lambda word: sum(
                unigram(d, word) + hints.get(code, {}).get(word, 0.0)
                for m, d in tagged if code in m["codes"]), reverse=True)
            assignment[code] = candidates[0] if start == 0 else rng.choice(candidates[:min(8, len(candidates))])
        for sweep in range(iterations):
            change = False
            for code in rng.sample(unknown_codes, len(unknown_codes)):
                current = assignment[code]
                counts = Counter(assignment.values()) if distinct else None
                bestword, best_delta = current, 0.0
                for word in choices:
                    value = change_delta(code, word, assignment, distinct_counts=counts)
                    if value > best_delta + 1e-9 or (abs(value - best_delta) < 1e-9 and word < bestword):
                        bestword, best_delta = word, value
                assignment[code] = bestword
                change |= bestword != current
            if distinct and len(unknown_codes) > 1:
                # Two-variable swap moves help leave local minima created by one-to-one constraints.
                for ai, ca in enumerate(unknown_codes):
                    for cb in unknown_codes[ai + 1:]:
                        if assignment[ca] == assignment[cb]:
                            continue
                        previous = score(assignment)
                        assignment[ca], assignment[cb] = assignment[cb], assignment[ca]
                        if score(assignment) > previous + 1e-8:
                            change = True
                        else:
                            assignment[ca], assignment[cb] = assignment[cb], assignment[ca]
            if not change:
                break
        val = score(assignment)
        if val > best_score:
            best_score, best_assign = val, assignment.copy()

    proposals = {}
    for code in all_codes:
        if code in anchors:
            proposals[code] = {"term": anchors[code], "status": "verified_alignment", "alternatives": [], "evidence": "Explicit segmented known plaintext/ciphertext pair"}
            continue
        scores = []
        counts = Counter(best_assign.values()) if distinct else None
        for word in choices:
            value = best_score + change_delta(code, word, best_assign, distinct_counts=counts)
            scores.append((round(value, 5), word))
        scores.sort(key=lambda item: (-item[0], item[1]))
        gap = scores[0][0] - scores[1][0] if len(scores) > 1 else 0
        proposals[code] = {
            "term": scores[0][1],
            "status": "hypothesis_unverified",  # scores are NOT calibrated probabilities
            "score_gap_to_second": round(gap, 4),
            "alternatives": [{"term": w, "relative_score": round(s - scores[0][0], 4)} for s, w in scores[:5]],
            "evidence": "Metadata-conditioned lexical frequencies and phrase transitions; must be independently checked"
        }
    decoded = []
    for m, d in tagged:
        pieces = [proposals[c]["term"] for c in m["codes"]]
        decoded.append({
            "id": m["id"], "domain_inferred": d, "codes": m["codes"],
            "suggested_segments": pieces, "reading": "".join(pieces),
            "verified_codes": sum(c in anchors for c in m["codes"]),
            "total_codes": len(m["codes"]),
            "warning": "Any segment not grounded in an explicit known pair is a hypothesis."
        })
    return {
        "case_id": case.get("case_id", "unnamed"),
        "model": "lexical + bigram constrained coordinate search (not a trained cryptanalytic LLM)",
        "metadata_used": use_metadata,
        "distinct_phrases_assumed": distinct,
        "verified_anchors": anchors,
        "pair_review": reviews,
        "code_frequency": dict(freq.most_common()),
        "known_code_count": len(anchors),
        "unknown_code_count": len(unknown_codes),
        "objective_score": round(best_score, 5),
        "proposals": proposals,
        "decoded_messages": decoded,
        "limitations": [
            "No reliable mapping from code group count to Chinese character count is assumed.",
            "Unknown outputs are unverified hypotheses; score gaps are not probabilities.",
            "A known plaintext without explicit code-to-phrase segmentation remains a manual review item.",
            "This prototype assumes fixed tokenized code groups without an extra additive cipher layer.",
            "Language statistics can be wrong if sample text does not represent the historical communication style."
        ]
    }


def evaluate_demo(result: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Never consult ground_truth in analyze(): evaluation only, strictly separate."""
    truth = case.get("ground_truth", {})
    anchors = result["verified_anchors"]
    unverified = [(c, t) for c, t in truth.items() if c not in anchors and c in result["proposals"]]
    correct = sum(result["proposals"][c]["term"] == t for c, t in unverified)
    in_top_five = sum(t in [a["term"] for a in result["proposals"][c]["alternatives"]] for c, t in unverified)
    return {
        "demo_only_not_real_world_accuracy": True,
        "held_out_codes": len(unverified),
        "correct_top_1": correct,
        "correct_top_5": in_top_five,
        "top_1_rate": round(correct / len(unverified), 4) if unverified else None,
        "top_5_rate": round(in_top_five / len(unverified), 4) if unverified else None,
        "note": "Ground truth was used for scoring after inference and not included in its inputs. This is one artificial case, not a scientific benchmark."
    }
