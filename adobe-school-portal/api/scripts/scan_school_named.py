#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
from app.services.excel_import import load_named_by_school_contact, load_named_seats_by_contact  # noqa: E402
from app.services.named_kpis import find_named_mail_path  # noqa: E402

keywords = ("목동", "서라벌")

for term in ("CY25-H2", "CY26-H1"):
    path = find_named_mail_path(term)
    print(f"\n=== {term} {path} ===")
    if not path:
        continue
    for (sk, cn), emails in load_named_by_school_contact(path).items():
        if any(k in sk for k in keywords):
            seats = load_named_seats_by_contact(path).get((sk, cn), "?")
            print(f"  school={sk!r} contact={cn!r} seats={seats} emails={len(emails)}")
