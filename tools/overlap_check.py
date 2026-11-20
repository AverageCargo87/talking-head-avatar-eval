#!/usr/bin/env python3
"""Copyright guard: does a script share a run of N identical words with a source text?

    python tools/overlap_check.py --texts lines.txt --corpus book.pdf pages.json notes.txt [--n 8]

Every published line of narration or dialogue goes through this before its audio is
released. Text is normalised (lower case, the Russian letter yo folded into ye, punctuation
removed), every N-word window of the corpus goes into a set, and each line of ``--texts``
fails if any of its N-word windows is in that set. Default N = 8.

Corpus formats: .txt, .json (every string value, or only the values of ``--json-field``),
.pdf (needs PyMuPDF). The corpus is read locally and never copied anywhere; the report shows
only the overlapping windows so they can be rewritten.
"""
import argparse
import json
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def normalise(text: str) -> list:
    t = text.lower().replace("ё", "е")      # yo -> ye
    t = re.sub(r"[^\w\s]", " ", t).replace("_", " ")
    return t.split()


def json_strings(o, field=None, inside=False):
    if isinstance(o, str):
        if field is None or inside:
            yield o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from json_strings(v, field, inside or (field is not None and k == field))
    elif isinstance(o, list):
        for v in o:
            yield from json_strings(v, field, inside)


def read_corpus(path: str, json_field=None) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        with open(path, encoding="utf-8") as f:
            return "\n".join(json_strings(json.load(f), json_field))
    if ext == ".pdf":
        import fitz  # PyMuPDF
        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def ngrams(words: list, n: int) -> set:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def check(lines: list, corpus_paths: list, n: int = 8, json_field=None):
    grams = set()
    words_total = 0
    for p in corpus_paths:
        w = normalise(read_corpus(p, json_field))
        words_total += len(w)
        grams |= ngrams(w, n)
    report = []
    for line in lines:
        w = normalise(line)
        hits = [" ".join(w[i:i + n]) for i in range(len(w) - n + 1) if tuple(w[i:i + n]) in grams]
        report.append({"line": line, "pass": not hits, "overlaps": hits})
    return words_total, len(grams), report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--texts", required=True, help="UTF-8 file, one line of script per line")
    ap.add_argument("--corpus", nargs="+", required=True)
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--json-field", help="only use JSON values under this key (e.g. show)")
    a = ap.parse_args()
    with open(a.texts, encoding="utf-8") as f:
        lines = [x.strip() for x in f if x.strip()]
    words, grams, report = check(lines, a.corpus, a.n, a.json_field)
    print(f"corpus: {len(a.corpus)} files, {words} words, {grams} distinct {a.n}-word windows")
    for r in report:
        print(f"[{'PASS' if r['pass'] else 'FAIL'}] {r['line'][:72]}")
        for h in r["overlaps"][:5]:
            print(f"      shared: '{h}'")
    failed = sum(not r["pass"] for r in report)
    print("RESULT:", "ALL PASS" if not failed else f"{failed} FAIL")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
