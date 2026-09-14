#!/usr/bin/env python3
"""Optional PDF worker. Invoke with the discovered PDF-capable interpreter."""
import argparse
import importlib.metadata
import json
from pathlib import Path


def extract(path, tables=False):
    import pymupdf
    pages = []
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise ValueError("encrypted_pdf: supply an authorized unlocked copy")
        for page in doc:
            text = page.get_text("text", sort=True)
            item = {"locator": f"page:{page.number + 1}", "text": text,
                    "page_number": page.number + 1, "tables": [],
                    "warnings": [] if text.strip() else ["no_text: visual review or OCR needed"]}
            if tables:
                try:
                    for table in page.find_tables().tables:
                        item["tables"].append({"bbox": list(table.bbox), "cells": table.extract()})
                except Exception as exc:
                    item["warnings"].append(f"table_extraction_failed:{type(exc).__name__}")
            pages.append(item)
    return {"format": "pdf", "extractor": "pymupdf",
            "extractor_version": importlib.metadata.version("pymupdf"),
            "pages": pages, "visual_reviewed": False, "ocr_performed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("output")
    parser.add_argument("--tables", action="store_true")
    args = parser.parse_args()
    result = extract(args.path, args.tables)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
