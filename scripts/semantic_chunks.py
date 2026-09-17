"""Token-budgeted semantic windows; stdlib only until the worker loads a model.

Offsets refer to the exact input string. A parent can have several independently
scored windows: averaging them would hide a relevant passage at the end.
"""
from __future__ import annotations

import math
import struct

WINDOW_VERSION = 2


def token_windows(text, tokenizer, maximum, overlap=16):
    """Cover all input characters without relying on silent tokenizer truncation.

    Count *actual* tokens including special tokens. Binary search is only a
    sizing heuristic (token counts need not be monotonic); every returned slice
    is independently checked. This also works with slow tokenizers.
    """
    if not isinstance(text, str):
        raise ValueError("semantic input must be text")
    if type(maximum) is not int or maximum < 2:
        raise ValueError("invalid model token limit")
    if type(overlap) is not int or overlap < 0:
        raise ValueError("invalid token overlap")

    def count(value, special=True):
        ids = tokenizer(value, add_special_tokens=special, truncation=False,
                        return_attention_mask=False)["input_ids"]
        return len(ids)

    if count("") > maximum:
        raise ValueError("special tokens exceed model token limit")
    if not text:
        return [{"start": 0, "end": 0, "token_count": count("")}]
    windows, start = [], 0
    overlap = min(overlap, max(0, (maximum - count("")) // 4))
    while start < len(text):
        end = len(text)
        if count(text[start:end]) > maximum:
            low, high, end = start + 1, len(text), start
            while low <= high:
                middle = (low + high) // 2
                if count(text[start:middle]) <= maximum:
                    end, low = middle, middle + 1
                else:
                    high = middle - 1
            if end == start:
                raise ValueError("one character exceeds model token budget")
            # Prefer a nearby word/line boundary, but recheck the actual slice.
            boundary = max(text.rfind(" ", start + (end-start)//2, end),
                           text.rfind("\n", start + (end-start)//2, end))
            if boundary >= start and count(text[start:boundary+1]) <= maximum:
                end = boundary + 1
        tokens = count(text[start:end])
        if end <= start or tokens > maximum:
            raise ValueError("semantic window would be truncated")
        windows.append({"start": start, "end": end, "token_count": tokens})
        if end == len(text):
            break
        next_start = end
        if overlap:
            low, high = start + 1, end
            while low <= high:
                middle = (low + high) // 2
                if count(text[middle:end], False) <= overlap:
                    next_start, high = middle, middle - 1
                else:
                    low = middle + 1
            if count(text[next_start:end], False) > overlap:
                next_start = end
        start = max(start + 1, next_start)
    return windows


def validate_spans(spans, texts, maximum):
    """Verify the worker/storage manifest covers each exact input without gaps."""
    if type(maximum) is not int or maximum < 2 or not isinstance(spans, list):
        raise ValueError("invalid semantic window manifest")
    grouped = [[] for _ in texts]
    previous = -1
    for span in spans:
        if not isinstance(span, dict):
            raise ValueError("invalid semantic span")
        idx, start, end, tokens = (span.get(k) for k in ("input", "start", "end", "token_count"))
        if any(type(v) is not int for v in (idx, start, end, tokens)):
            raise ValueError("semantic span fields must be integers")
        if not 0 <= idx < len(texts) or idx < previous:
            raise ValueError("invalid semantic input order")
        if not 0 <= start <= end <= len(texts[idx]) or not 0 <= tokens <= maximum:
            raise ValueError("semantic span outside input/token budget")
        rows = grouped[idx]
        if (not rows and start != 0) or (rows and (start > rows[-1]["end"] or start <= rows[-1]["start"] or end <= rows[-1]["end"])):
            raise ValueError("semantic spans have gaps or do not advance")
        if start == end and (texts[idx] or rows):
            raise ValueError("empty semantic span")
        rows.append(span)
        previous = idx
    if any(not rows or rows[-1]["end"] != len(text) for rows, text in zip(grouped, texts)):
        raise ValueError("semantic windows do not cover full input")
    return grouped


def normalized(vector, dimension):
    if not isinstance(vector, (list, tuple)) or len(vector) != dimension:
        raise ValueError("invalid semantic window dimension")
    if any(type(v) not in {float, int} or not math.isfinite(v) for v in vector):
        raise ValueError("invalid semantic window vector")
    if not math.isclose(math.sqrt(sum(v*v for v in vector)), 1., abs_tol=1e-4):
        raise ValueError("semantic window vector is not normalized")
    return vector


def pack_tail(vectors, dimension):
    values = [v for vector in vectors[1:] for v in normalized(vector, dimension)]
    return struct.pack("<" + "f" * len(values), *values)


def unpack_tail(blob, count, dimension):
    if len(blob) != 4 * count * dimension:
        raise ValueError("stored semantic window bytes have invalid length")
    values = struct.unpack("<" + "f" * (count * dimension), blob)
    return [normalized(values[n:n+dimension], dimension) for n in range(0, len(values), dimension)]
