"""Explicit LLM-first candidate-vocabulary generation from observable ciphertext/context.

Critically, no seeded lexicon, sample plaintext, codebook, or gold is read or
passed to this stage. Candidate words are not code->plaintext alignments.
"""
from __future__ import annotations

from collections import Counter
import time
from typing import Any, Callable

from .agent import query_local_llm, validate_llm_endpoint
from .core import CaseError, validate_case
from .llm_evidence import safe_message_metadata



def make_vocabulary_packet(case: dict, *, metadata: bool, limit_samples: int = 24) -> dict:
    """Only ciphertext frequency statistics and optionally whitelisted side information."""
    validate_case(case)
    if case.get('known_pairs') or any(x in case for x in ('gold','ground_truth','codebook')):
        raise CaseError('cold-start vocabulary requires unknown mappings and no embedded gold')
    messages = case['messages']
    freq = Counter(c for m in messages for c in m['codes'])
    samples = []
    if metadata:
        # Sample across the whole time/arrival window, not just the first 25.
        count = min(limit_samples, len(messages))
        indexes = [(i * (len(messages) - 1)) // max(1, count - 1) for i in range(count)]
        for i in indexes:
            m = messages[i]
            samples.append(safe_message_metadata(m))
    return {
        'task': 'generate_vocabulary',
        'policy': ('All code-to-text relationships are unknown. Propose possible vocabulary '
                   'from contextual evidence and ordinary language knowledge, not secret answers. '
                   'A candidate term is never a verified code mapping.'),
        'corpus_statistics': {
            'messages_count': len(messages),
            'unique_cipher_groups': len(freq),
            'message_lengths': [len(m['codes']) for m in messages],
            'code_frequencies': dict(freq.most_common(150)),
        },
        'metadata_enabled': metadata,
        'side_information_samples': samples,
        'requested_max_terms': 128,
        'requested_max_patterns': 30,
    }


def generate_vocabulary(case: dict, *, metadata: bool, llm_settings: dict,
                        capture_io: bool = False, progress: Callable[[str], None] = print,
                        query: Callable[..., dict] = query_local_llm) -> tuple[dict, dict]:
    """Make exactly one explicit LLM call, returning a solver-ready case plus audit.

    The supplied profile lexicon/keyword/sentences are intentionally discarded.
    Both subsequent solver branches then use the *same* generated candidates.
    """
    url, model = llm_settings['base_url'], llm_settings['model']
    validate_llm_endpoint(url,allow_private_network=llm_settings.get('allow_private_network',False),
                          allowed_hosts=llm_settings.get('allowed_hosts', []))
    packet = make_vocabulary_packet(case, metadata=metadata)
    record: dict[str, Any] = {'task':'generate_vocabulary','model':model,
                              'metadata_enabled':metadata,'messages':len(case['messages'])}
    if capture_io:
        record['exchanges'] = []
        def capture(stage: str, payload: dict) -> None:
            record['exchanges'].append({'stage':stage,**payload})
    else:
        capture = None
    started = time.monotonic()
    progress(f'[vocab] LLM generating candidate terms from {len(case["messages"])} ciphertexts '
             f'and {len(packet["side_information_samples"])} contextual records ...')
    try:
        reply = query(url,model,packet,timeout=llm_settings.get('timeout_seconds',90),
                      allow_private_network=llm_settings.get('allow_private_network',False),
                      allowed_hosts=llm_settings.get('allowed_hosts', []),
                      api_key_env=llm_settings.get('api_key_env'),on_exchange=capture)
        entries = reply.get('vocabulary')
        if not isinstance(entries,list):
            raise CaseError('LLM vocabulary reply must contain vocabulary array')
        terms: list[str] = []
        reasons: dict[str,str] = {}
        for item in entries:
            if isinstance(item,dict):
                word, reason = item.get('term'),item.get('reason','')
            else:
                word,reason = item,''
            if not isinstance(word,str):
                continue
            word = word.strip()
            if not 1 <= len(word) <= 24 or any(ord(ch)<32 for ch in word) or word in terms:
                continue
            terms.append(word)
            reasons[word] = str(reason)[:250]
            if len(terms)>=128:
                break
        if len(terms)<5:
            raise CaseError('LLM supplied fewer than five valid terms; no fixed vocabulary fallback')
        patterns = []
        for item in reply.get('patterns',[]):
            if not isinstance(item,list) or not 2 <= len(item)<=24:
                continue
            if all(isinstance(w,str) and w in terms for w in item):
                patterns.append(item)
                if len(patterns)>=30:
                    break
        # Base language model includes these generated patterns; nothing from
        # the synthetic corpus generator's gold-aware domain profiles survives.
        generated = case_from_vocabulary_record(case, {'terms':[{'term':w} for w in terms],
                                                       'patterns':patterns})
        record.update({'status':'completed','elapsed_seconds':round(time.monotonic()-started,3),
                       'terms':[{'term':w,'reason':reasons[w]} for w in terms],
                       'patterns':patterns, 'candidate_count':len(terms),
                       'discarded_manual_profiles':True})
        progress(f'[vocab] Generated {len(terms)} distinct candidates, {len(patterns)} language patterns '
                 f'(not verified code mappings)')
        return generated, record
    except Exception as exc:
        record.update({'status':'failed','elapsed_seconds':round(time.monotonic()-started,3),
                       'error_type':type(exc).__name__,'error_summary':str(exc)[:300]})
        # Avoid silent fallback to gold-bearing seeded lexicons.
        setattr(exc,'vocabulary_record',record)
        raise


def case_from_vocabulary_record(case: dict, record: dict) -> dict:
    """Offline replay: replace any manually provided lexicon with recorded LLM terms."""
    terms = [i['term'] for i in record['terms']]
    if not terms or len(terms)!=len(set(terms)):
        raise CaseError('invalid saved generated vocabulary')
    patterns = record.get('patterns',[])
    if not isinstance(patterns,list) or any(not isinstance(p,list) or
         any(w not in terms for w in p) for p in patterns):
        raise CaseError('invalid saved vocabulary patterns')
    generated=dict(case)
    generated['profiles'] = {
        'llm_generated_background': {
            'keywords': [],
            'lexicon': {word: max(1.0, 3.0 - i / max(1,len(terms)))
                        for i,word in enumerate(terms)},
            'sentences': patterns,
        }
    }
    return generated
