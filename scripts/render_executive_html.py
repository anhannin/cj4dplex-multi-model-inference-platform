#!/usr/bin/env python3
"""Render the Markdown summary into two explicit print sections; stdlib only."""

import html
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
text = (root / "docs/EXECUTIVE_SUMMARY.ko.md").read_text()
first, second = text.split("### 지속 요청에서 효과와 한계 확인", 1)
sections = [first, "### 지속 요청에서 효과와 한계 확인" + second]


def inline(s):
    s = html.escape(s)
    s = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^]]+)\]\(([^)]+)\)", r"\1", s)
    return s


def render(md):
    out = []
    table = False
    for line in md.splitlines():
        if line.startswith("|"):
            if re.match(r"^\|[-:| ]+\|$", line):
                continue
            if not table:
                out.append("<table>")
                table = True
            out.append(
                "<tr>"
                + "".join(
                    "<td>" + inline(c.strip()) + "</td>"
                    for c in line.strip("|").split("|")
                )
                + "</tr>"
            )
            continue
        if table:
            out.append("</table>")
            table = False
        if not line.strip():
            continue
        if line.startswith("### "):
            out.append("<h3>" + inline(line[4:]) + "</h3>")
        elif line.startswith("## "):
            out.append("<h2>" + inline(line[3:]) + "</h2>")
        elif line.startswith("# "):
            out.append("<h1>" + inline(line[2:]) + "</h1>")
        elif line.startswith("- "):
            out.append('<p class="bullet">• ' + inline(line[2:]) + "</p>")
        else:
            out.append("<p>" + inline(line) + "</p>")
    if table:
        out.append("</table>")
    return "\n".join(out)


content = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>CJ4DPLEX Executive Summary</title><style>
@page{size:A4;margin:15mm 16mm}body{font-family:'Noto Sans CJK JP',sans-serif;color:#172530;font-size:10pt;line-height:1.55;margin:0}section{break-after:page}section:last-child{break-after:auto}h1{font-size:20pt;margin:0 0 4mm}h2{font-size:13pt;margin:0 0 3mm}h3{font-size:11pt;margin:4mm 0 1.8mm;color:#235d76}p{margin:1.8mm 0}.bullet{margin:1.2mm 0}table{width:100%;border-collapse:collapse;font-size:9.5pt;margin:3mm 0}td{border:1px solid #bdc8cf;padding:2mm}tr:first-child{background:#e9f0f4;font-weight:700}strong{font-weight:700}footer{margin-top:3mm;font-size:8pt;color:#526570}
</style>"""
content += (
    "".join(
        "<section>"
        + render(md)
        + f"<footer>CJ 4DPLEX AI Platform · 안하민 · {i + 1}/2</footer></section>"
        for i, md in enumerate(sections)
    )
    + "</html>"
)
(root / "docs/EXECUTIVE_SUMMARY.ko.html").write_text(content)
