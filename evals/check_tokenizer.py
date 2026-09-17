#!/usr/bin/env python3
"""Opt-in actual tokenizer checks. No model weights or inference API are used."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from index import MODEL, MODEL_REVISION
from semantic_chunks import token_windows, validate_spans


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-download', action='store_true', help='allow tokenizer/config downloads only')
    args = parser.parse_args()
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer
    start = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=MODEL_REVISION,
                                               local_files_only=not args.allow_download)
    config = Path(hf_hub_download(MODEL, 'sentence_bert_config.json', revision=MODEL_REVISION,
                                 local_files_only=not args.allow_download))
    maximum = json.loads(config.read_text())['max_seq_length']
    texts = {
        'english_tail': 'Ordinary background context. ' * 120 + 'The only final result is TAILFACT.',
        'korean_tail': '이 문장은 반복되는 배경 설명입니다. ' * 120 + '마지막 근거는 정정된 정확도 94퍼센트입니다.',
        'mixed_tail': '근거 evidence 123. ' * 120 + '정정 결과 final result TAILFACT.',
        'unbroken': 'abcdefghijk한글😀' * 200,
        'whitespace': ' \n\t' * 500,
        'empty': '',
    }
    results = []
    for name, text in texts.items():
        spans = token_windows(text, tokenizer, maximum)
        validate_spans([{'input': 0, **span} for span in spans], [text], maximum)
        counts = [len(tokenizer(text[s['start']:s['end']], add_special_tokens=True,
                                truncation=False)['input_ids']) for s in spans]
        # Check the encoder's documented strip preprocessing as well.
        stripped = [len(tokenizer(text[s['start']:s['end']].strip(), add_special_tokens=True,
                                  truncation=False)['input_ids']) for s in spans]
        if max(counts + stripped) > maximum:
            raise AssertionError(f'{name}: token budget exceeded')
        results.append({'case': name, 'characters': len(text), 'windows': len(spans),
                        'max_window_tokens': max(counts), 'tail_covered': spans[-1]['end'] == len(text)})
    print(json.dumps({'status': 'passed', 'model': MODEL, 'revision': MODEL_REVISION,
                      'max_seq_length': maximum, 'python': platform.python_version(),
                      'transformers': importlib.metadata.version('transformers'),
                      'tokenizers': importlib.metadata.version('tokenizers'),
                      'seconds': time.perf_counter() - start, 'cases': results,
                      'limits': 'Tokenizer/window coverage only; no embedding ranking or agent-behavior evaluation.'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
