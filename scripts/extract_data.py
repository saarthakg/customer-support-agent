"""Convert `pdftotext -layout` output of the appendices PDF into the two JSON datasets.

    pdftotext -layout "Agent Building Prompt Appendices.pdf" appendices.txt
    python3 scripts/extract_data.py appendices.txt data

Fixes only PDF artifacts: drops the stray "None" line under each appendix heading,
and rejoins string values that the PDF wrapped across lines (with one space).
Every value is otherwise preserved exactly, typos included (DECISIONS D-01).
"""

import json
import sys
from pathlib import Path


def rejoin_wrapped_lines(chunk: str) -> str:
    lines: list[str] = []
    pending: str | None = None  # a line whose string literal hasn't closed yet
    for raw in chunk.splitlines():
        line = raw.strip()
        if line in ("", "None"):
            continue
        pending = line if pending is None else f"{pending} {line}"
        if pending.count('"') % 2 == 0:  # quotes balanced: the logical line is complete
            lines.append(pending)
            pending = None
    if pending is not None:
        raise ValueError(f"unterminated string: {pending!r}")
    return "\n".join(lines)


def main(source: Path, out_dir: Path) -> None:
    text = source.read_text(encoding="utf-8")
    orders_part, products_part = text.split("Appendix B: ProductCatalog.json")
    orders_part = orders_part.split("Appendix A: CustomerOrders.json")[1]
    for name, chunk in (("CustomerOrders.json", orders_part), ("ProductCatalog.json", products_part)):
        records = json.loads(rejoin_wrapped_lines(chunk))
        (out_dir / name).write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{name}: {len(records)} records")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
