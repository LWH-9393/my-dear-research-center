#!/usr/bin/env python3
"""Local token-window embeddings. JSON in/out; no remote inference API."""
from __future__ import annotations

import argparse
import json
import sys

from semantic_chunks import WINDOW_VERSION, token_windows, validate_spans


def encode_windows(model, texts, batch_size):
    maximum = model.max_seq_length
    if type(maximum) is not int:
        raise ValueError("model does not expose a finite token limit")
    spans, windows = [], []
    for idx, text in enumerate(texts):
        for span in token_windows(text, model.tokenizer, maximum):
            spans.append({"input": idx, **span})
            windows.append(text[span["start"]:span["end"]])
    validate_spans(spans, texts, maximum)
    # Explicit empty prompt prevents a saved default prompt changing the budget.
    vectors = model.encode(windows, batch_size=min(batch_size, max(1, len(windows))),
                           prompt="", convert_to_numpy=True,
                           normalize_embeddings=True, show_progress_bar=False)
    rows = vectors.astype("float32").tolist()
    return {"window_version": WINDOW_VERSION, "max_seq_length": maximum,
            "spans": spans, "vectors": rows,
            "dimension": len(rows[0]) if rows else model.get_sentence_embedding_dimension()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    request = json.load(sys.stdin)
    texts = request.get("texts")
    if not isinstance(texts, list) or any(not isinstance(x, str) for x in texts):
        raise ValueError("texts must be a list of strings")
    batch_size = request.get("batch_size", 32)
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(args.model, revision=args.revision,
                                local_files_only=args.offline)
    print(json.dumps({"model": args.model, "revision": args.revision,
                      **encode_windows(model, texts, batch_size)}))


if __name__ == "__main__":
    main()
