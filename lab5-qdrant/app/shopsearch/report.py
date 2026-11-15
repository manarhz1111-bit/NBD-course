from __future__ import annotations

from collections.abc import Sequence


def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    cells = [[str(h) for h in headers]] + [[str(c) for c in row] for row in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    rule = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def line(values: Sequence[str]) -> str:
        return "| " + " | ".join(v.rjust(w) if v.replace(".", "", 1).isdigit() else v.ljust(w) for v, w in zip(values, widths)) + " |"

    return [rule, line(cells[0]), rule, *[line(r) for r in cells[1:]], rule]
