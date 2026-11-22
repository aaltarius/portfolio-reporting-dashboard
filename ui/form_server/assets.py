"""ui/form_server/assets.py — file statici del form-server serviti in locale (nessuna rete, nessuna CDN).

Oggi: `plotly.min.js`, preso dal pacchetto Python `plotly` già installato (stessa libreria dei grafici dell'app).
"""
from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

router = APIRouter()


def _plotly_js_path() -> str:
    import plotly

    return os.path.join(os.path.dirname(plotly.__file__), "package_data", "plotly.min.js")


@router.get("/assets/plotly.min.js")
async def plotly_js():
    path = _plotly_js_path()
    if not os.path.exists(path):
        return Response(status_code=404)
    return FileResponse(path, media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=86400"})
