import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

nfo1 = Path(r"I:\Incoming\Vdo\scan\output\Daisie Belle\INTERVIEW-316\INTERVIEW-316.nfo")
nfo2 = Path(r"I:\Incoming\Vdo\scan\output\Audrey Madison\INTERVIEW-317\INTERVIEW-317.nfo")

for p in [nfo1, nfo2]:
    if p.exists():
        print(f"=== {p} ===")
        text = p.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            if any(
                k in line
                for k in ["<title>", "<originalfilename>", "<originalfilepath>", "<actor>", "<studio>", "<id>"]
            ):
                print(" ", line.strip())
    else:
        print(f"File not found: {p}")
