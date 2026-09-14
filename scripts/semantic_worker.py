#!/usr/bin/env python3
"""Local Sentence Transformers worker. JSON in/out; no remote inference API."""
from __future__ import annotations

import argparse
import json
import sys


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
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(
        args.model,
        revision=args.revision,
        local_files_only=args.offline,
    )
    batch_size = int(request.get("batch_size", 32))
    if batch_size < 1: raise ValueError("batch_size must be positive")
    vectors = model.encode(
        texts,
        batch_size=min(batch_size, max(1, len(texts))),
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    rows = vectors.astype("float32").tolist()
    print(json.dumps({
        "model": args.model,
        "revision": args.revision,
        "dimension": len(rows[0]) if rows else model.get_sentence_embedding_dimension(),
        "vectors": rows,
    }))


if __name__ == "__main__":
    main()
