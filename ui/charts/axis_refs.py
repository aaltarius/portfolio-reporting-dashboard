from __future__ import annotations


def trace_xaxis_layout_name(trace) -> str:
    """Converte il riferimento asse X di una traccia nel nome layout Plotly."""
    try:
        ref = str(getattr(trace, "xaxis", None) or "x")
        if ref == "x":
            return "xaxis"
        if ref.startswith("x") and ref[1:].isdigit():
            return f"xaxis{ref[1:]}"
    except Exception:
        pass
    return "xaxis"


def trace_yaxis_layout_name(trace) -> str:
    """Converte il riferimento asse Y di una traccia nel nome layout Plotly."""
    try:
        ref = str(getattr(trace, "yaxis", None) or "y")
        if ref == "y":
            return "yaxis"
        if ref.startswith("y") and ref[1:].isdigit():
            return f"yaxis{ref[1:]}"
    except Exception:
        pass
    return "yaxis"
