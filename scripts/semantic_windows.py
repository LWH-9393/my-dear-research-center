"""Token-bounded, source-preserving semantic windows and their wire contract.

No model dependency is imported here. Counts use the actual loaded tokenizer,
with special tokens, rather than an estimated characters-to-tokens ratio.
"""
from __future__ import annotations

import hashlib
import math
import re

WINDOW_VERSION = 2


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def token_windows(text, tokenizer, max_seq_length, overlap_tokens=16, normalize=None):
    """Return overlapping original-character spans; never silently truncate.

    Bisection chooses a fitting substring, followed by an exact token-count
    check. This also supports slow tokenizers and avoids decoding partial
    byte/subword tokens back into damaged Unicode. Tokenization need not be
    monotonic: bisection is a sizing heuristic, not the safety check.
    """
    if not isinstance(text, str):
        raise ValueError("semantic input must be text")
    if type(max_seq_length) is not int or max_seq_length < 1:
        raise ValueError("model must declare a positive maximum sequence length")
    if type(overlap_tokens) is not int or overlap_tokens < 0:
        raise ValueError("overlap_tokens must be a nonnegative integer")
    normalize = normalize or (lambda value: value)

    def count(value, special=True):
        return len(tokenizer.encode(normalize(value.strip()), add_special_tokens=special,
                                    truncation=False, verbose=False))

    special = count("")
    if special >= max_seq_length:
        raise ValueError("model limit leaves no room for input tokens")
    overlap = min(overlap_tokens, max(0, (max_seq_length-special) // 4))
    if not text:
        return [{"start": 0, "end": 0, "token_count": special}]
    result, start, previous_end = [], 0, 0
    while start < len(text):
        end = len(text)
        if count(text[start:end]) > max_seq_length:
            low, high, best = start+1, end, start
            while low <= high:
                middle = (low+high) // 2
                if count(text[start:middle]) <= max_seq_length:
                    best, low = middle, middle+1
                else:
                    high = middle-1
            end = best
            # Prefer a word/sentence boundary without sacrificing progress.
            boundaries = list(re.finditer(r"\s+|[.!?。！？]", text[start:end]))
            if boundaries:
                boundary = start+boundaries[-1].end()
                if boundary > max(previous_end, start+(end-start)//2):
                    if count(text[start:boundary]) <= max_seq_length:
                        end = boundary
        if end <= previous_end:
            if start < previous_end:
                start = previous_end  # Drop overlap, never drop unseen content.
                continue
            raise ValueError("a source character cannot fit the model token limit")
        actual = count(text[start:end])
        if actual > max_seq_length:
            raise ValueError("token window exceeds the model input limit")
        result.append({"start": start, "end": end, "token_count": actual})
        previous_end = end
        if end == len(text):
            break
        next_start = end
        if overlap:
            low, high = start+1, end
            while low <= high:
                middle = (low+high) // 2
                if count(text[middle:end], special=False) <= overlap:
                    next_start, high = middle, middle-1
                else:
                    low = middle+1
            # Recheck: context-dependent tokenizers are not monotonic.
            if count(text[next_start:end], special=False) > overlap:
                next_start = end
        start = max(start+1, next_start)
    return result


def unit_vector(value, dimension):
    if (not isinstance(value, list) or len(value) != dimension
            or any(type(x) not in {int, float} or not math.isfinite(x) for x in value)):
        raise ValueError("invalid semantic window vector")
    if not math.isclose(math.sqrt(sum(x*x for x in value)), 1., abs_tol=1e-4):
        raise ValueError("semantic window vector is not normalized")
    return value


def validate_windows(payload, text, dimension):
    """Check a complete window manifest, including gaps, bounds and vectors."""
    if not isinstance(payload, dict) or payload.get("version") != WINDOW_VERSION:
        raise ValueError("semantic window protocol mismatch; rebuild with the current worker")
    if payload.get("text_sha256") != text_sha(text):
        raise ValueError("semantic window source hash mismatch")
    limit = payload.get("max_seq_length")
    if type(limit) is not int or limit < 1:
        raise ValueError("invalid semantic window token limit")
    windows = payload.get("windows")
    if not isinstance(windows, list) or not windows:
        raise ValueError("semantic windows are missing")
    previous_end = 0
    previous_start = -1
    for position, window in enumerate(windows):
        if not isinstance(window, dict):
            raise ValueError("semantic window must be an object")
        start, end, count = (window.get(k) for k in ("start", "end", "token_count"))
        if (type(start) is not int or type(end) is not int
                or not 0 <= start <= end <= len(text)
                or (position == 0 and start != 0)
                or start > previous_end or start <= previous_start
                or (text and end <= previous_end)):
            raise ValueError("semantic window gap, order or source bounds are invalid")
        if type(count) is not int or not 0 <= count <= limit:
            raise ValueError("semantic window token count exceeds its limit")
        unit_vector(window.get("vector"), dimension)
        previous_start, previous_end = start, end
    if previous_end != len(text):
        raise ValueError("semantic windows do not cover the source tail")
    return windows


def encode_windowed(model, texts, batch_size=32):
    """Encode every window once; preserve vectors and original source offsets."""
    limit = model.max_seq_length
    first = model[0]
    normalize = str.lower if getattr(first, "do_lower_case", False) else None
    manifests, inputs = [], []
    for text in texts:
        windows = token_windows(text, model.tokenizer, limit, normalize=normalize)
        manifests.append({"version": WINDOW_VERSION, "text_sha256": text_sha(text),
                          "max_seq_length": limit, "windows": windows})
        inputs.extend(text[w["start"]:w["end"]] for w in windows)
    if not inputs:
        return [], [], model.get_sentence_embedding_dimension()
    vectors = model.encode(inputs, batch_size=min(batch_size, len(inputs)),
                           convert_to_numpy=True, normalize_embeddings=True,
                           show_progress_bar=False, prompt="").astype("float32").tolist()
    if len(vectors) != len(inputs):
        raise ValueError("model returned the wrong number of window embeddings")
    dimension = len(vectors[0])
    summaries, cursor = [], 0
    for text, manifest in zip(texts, manifests):
        group = vectors[cursor:cursor+len(manifest["windows"])]
        cursor += len(group)
        for window, vector in zip(manifest["windows"], group):
            window["vector"] = unit_vector(vector, dimension)
        summed = [sum(vector[d] for vector in group) for d in range(dimension)]
        norm = math.sqrt(sum(x*x for x in summed))
        if not math.isfinite(norm) or norm < 1e-12:
            raise ValueError("window summary cannot be normalized")
        summaries.append([x/norm for x in summed])
        validate_windows(manifest, text, dimension)
    return summaries, manifests, dimension
