"""Synthetic window manifests for protocol/lifecycle tests, NOT real embeddings."""
from semantic_windows import WINDOW_VERSION, text_sha


def with_windows(result, texts):
    """Add explicit synthetic single-window metadata to a fake worker result.

    token_count=1 is a fixture value, not a tokenizer measurement. Actual token
    splitting is tested separately and the real-model smoke test is opt-in.
    """
    result = dict(result)
    result["windows"] = [{"version": WINDOW_VERSION, "text_sha256": text_sha(text),
                          "max_seq_length": 128,
                          "windows": [{"start": 0, "end": len(text), "token_count": 1,
                                       "vector": vector}]}
                         for text, vector in zip(texts, result["vectors"])]
    return result
