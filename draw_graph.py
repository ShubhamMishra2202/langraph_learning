"""Render graph.png from the compiled graph, annotated with what LangGraph's own drawing hides.

LangGraph draws each ToolNode as a single box, so this lists the tools inside every
*_tools node and marks ask_user as the interrupt point. Needs Graphviz's `dot` on PATH.

    venv/bin/python draw_graph.py
"""
import subprocess

from graph import graph
from tools import FLIGHT_TOOLS, HOTEL_TOOLS, ITINERARY_TOOLS

TOOL_NODES = {"flight_tools": FLIGHT_TOOLS, "hotel_tools": HOTEL_TOOLS, "itinerary_tools": ITINERARY_TOOLS}
NODE_STYLE = 'shape=box style="rounded,filled" fillcolor="#f2f0ff" fontname="Helvetica"'


def node_label(name: str) -> str:
    if name in TOOL_NODES:
        rows = "".join(
            f'<tr><td align="left"><font point-size="11">• {t.name}</font></td></tr>'
            for t in TOOL_NODES[name]
        )
        return (
            '<<table border="0" cellspacing="2">'
            f'<tr><td><b>{name}</b></td></tr>'
            '<tr><td><font point-size="10" color="#555555">ToolNode: LLM picks any of</font></td></tr>'
            f"{rows}</table>>"
        )
    if f"{name}_tools" in TOOL_NODES:
        return f'<{name}<br/><font point-size="10" color="#555555">LLM + bind_tools</font>>'
    if name == "ask_user":
        return '<ask_user<br/><font point-size="10" color="#555555">interrupt() ⏸</font>>'
    return f'"{name}"'


def to_dot() -> str:
    g = graph.get_graph()
    lines = ["digraph G {", "  rankdir=TB;", '  edge [fontname="Helvetica" fontsize=10];']
    for node_id in g.nodes:
        if node_id == "__start__":
            lines.append('  "__start__" [shape=ellipse fontname="Helvetica"];')
        elif node_id == "__end__":
            lines.append('  "__end__" [shape=ellipse style=filled fillcolor="#bfb6fc" fontname="Helvetica"];')
        else:
            lines.append(f'  "{node_id}" [{NODE_STYLE} label={node_label(node_id)}];')
    for e in g.edges:
        attrs = []
        if e.conditional:
            attrs.append("style=dashed")
        if e.data and e.data != e.target:
            attrs.append(f'label="{e.data}"')
        lines.append(f'  "{e.source}" -> "{e.target}" [{" ".join(attrs)}];')
    lines.append("}")
    return "\n".join(lines)


if __name__ == "__main__":
    subprocess.run(["dot", "-Tpng", "-Gdpi=110", "-o", "graph.png"], input=to_dot().encode(), check=True)
    print("wrote graph.png")
