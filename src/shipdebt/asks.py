"""Collect the open "a human must do this" lines that agents leave in handoff notes,
so they can be cleared in one batched desk run instead of one ping each."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .scan import SKIP_DIRS

DEFAULT_PATTERNS = [
    r"\bNEEDS[ _-][A-Z]{3,}\s*[:\-–—]\s*\w",  # "NEEDS SAMMY: <what>", "NEEDS_OWNER - <what>"
    r"\b(?:waiting|waits) (?:on|for) (?:the )?(?:owner|human|you|approval|sign-?off)\b",
    r"\bready to (?:ship|publish|deploy|merge|submit)\b",
    r"\bawaiting (?:approval|review|deploy|merge|sign-?off)\b",
    r"\b(?:owner|human) (?:step|action) required\b",
    r"\bmay I (?:deploy|merge|publish|push)\b",
]
VERBS = [  # first match wins: money and accounts before the generic verbs
    ("pay", r"\bpay\b|purchase|\bbuy\b|\bfee\b|credit card|\bUSD\b|\$\d"),
    ("account", r"sign[ -]?up|\baccount\b|log ?in\b|two-factor|\b2fa\b|api key|\btoken\b"),
    ("deploy", r"deploy|go live|release"),
    ("merge", r"merge|pull request|\bPR\b"),
    ("publish", r"publish|submit|listing|store|upload"),
    ("decide", r"decide|choose|pick|approve|approval|sign-?off|review"),
]
DONE_MARKERS = re.compile(r"^\s*[-*]\s*\[x\]|~~|\b(?:DONE|RESOLVED|CLOSED)\b|\(done\)", re.I)
# Lines that talk ABOUT asks (rules, prompts, templates) rather than making one.
META = re.compile(r"[`\"'“]NEEDS[ _-][A-Z]+|NEEDS[ _-][A-Z]+:?[`\"'”]|"
                  r"NEEDS[ _-][A-Z]+\s*:\s*(?:none|n/?a|nothing|-)\b|NEEDS[ _-][A-Z]+ lines?\b", re.I)
TEXT_EXT = (".md", ".txt", ".markdown", ".rst")
MAX_BYTES = 1_000_000


@dataclass
class Ask:
    path: str
    line_no: int
    text: str
    verb: str


def classify(text: str) -> str:
    for verb, pat in VERBS:
        if re.search(pat, text, re.I):
            return verb
    return "other"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[`*_>#-]", " ", text)).strip().lower()


def find_asks(roots: list[str], patterns: list[str] | None = None, max_depth: int = 6,
              extensions: tuple[str, ...] = TEXT_EXT) -> tuple[list[Ask], int]:
    """Return (unique open asks, duplicate count)."""
    regex = re.compile("|".join(f"(?:{p})" for p in (patterns or DEFAULT_PATTERNS)))
    seen: set[str] = set()
    asks: list[Ask] = []
    dupes = 0
    for root in roots:
        root = os.path.abspath(root)
        base = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath.rstrip("\\/").count(os.sep) - base
            dirnames[:] = [] if depth >= max_depth else [
                d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if not fn.lower().endswith(extensions):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(path) > MAX_BYTES:
                        continue
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        lines = fh.readlines()
                except OSError:
                    continue
                for i, line in enumerate(lines, 1):
                    if not regex.search(line) or DONE_MARKERS.search(line) or META.search(line):
                        continue
                    text = line.strip()[:300]
                    key = _norm(text)
                    if key in seen:
                        dupes += 1
                        continue
                    seen.add(key)
                    asks.append(Ask(path=path, line_no=i, text=text, verb=classify(text)))
    return asks, dupes
