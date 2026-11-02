"""Convert pdftotext -layout output of the appendices into JSON files.

Only fixes PDF artifacts: drops the stray 'None' line under each heading and
rejoins string literals that the PDF wrapped across lines (joined with one space).
"""
import json, sys
src, out_dir = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
a_part, b_part = text.split("Appendix B: ProductCatalog.json")
a_part = a_part.split("Appendix A: CustomerOrders.json")[1]

def rejoin(chunk: str) -> str:
    out, buf = [], None
    for raw in chunk.splitlines():
        line = raw.strip()
        if line in ("", "None"):
            continue
        if buf is None:
            buf = line
        else:
            buf = buf + " " + line  # continuation of a wrapped string
        if buf.count('"') % 2 == 0:  # string literals balanced -> line complete
            out.append(buf)
            buf = None
    assert buf is None, f"unterminated string: {buf!r}"
    return "\n".join(out)

for name, chunk in (("CustomerOrders.json", a_part), ("ProductCatalog.json", b_part)):
    data = json.loads(rejoin(chunk))
    with open(f"{out_dir}/{name}", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(name, len(data))
