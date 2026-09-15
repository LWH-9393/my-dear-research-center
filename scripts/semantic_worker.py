#!/usr/bin/env python3
"""Local, token-windowed Sentence Transformers worker. No remote inference."""
from __future__ import annotations

import argparse
import json
import sys

from semantic_windows import encode_windowed


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
                                local_files_only=args.offline, trust_remote_code=False)
    vectors, windows, dimension = encode_windowed(model, texts, batch_size)
    print(json.dumps({"model": args.model, "revision": args.revision,
                      "dimension": dimension, "vectors": vectors, "windows": windows},
                     allow_nan=False))


if __name__ == "__main__":
    main()
