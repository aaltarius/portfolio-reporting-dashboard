"""ui/form_server — Mini-server FastAPI per inserimento operazioni senza rerun Streamlit.

Porta default 8502. Avviato in background da app.py via start_form_server().
Condivide la stessa pipeline di storage dell'app principale: nessuna logica duplicata.
Streamlit rileva le modifiche al JSON tramite StateManager.reload_if_changed() al
successivo rerun (o al click di qualsiasi widget).

Le pagine vivono come moduli separati in questo package (uno per route/pagina:
inserisci, strumenti, gestione, export_pp, privacy, sator, scheda_strumento),
assemblati qui in un'unica FastAPI app tramite APIRouter.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger("portafoglio.form_server")

FORM_PORT = 8502

_started = threading.Event()


def _build_fastapi_app():
    from fastapi import FastAPI

    _app = FastAPI(title="Portafoglio Form", docs_url=None, redoc_url=None)

    from ui.form_server.privacy import router as _privacy_router
    from ui.form_server.export_pp import router as _export_pp_router
    from ui.form_server.inserisci import router as _inserisci_router
    from ui.form_server.scheda_strumento import router as _scheda_strumento_router
    from ui.form_server.gestione import router as _gestione_router
    from ui.form_server.sator import router as _sator_router
    from ui.form_server.strumenti import router as _strumenti_router
    _app.include_router(_privacy_router)
    _app.include_router(_export_pp_router)
    _app.include_router(_inserisci_router)
    _app.include_router(_scheda_strumento_router)
    _app.include_router(_gestione_router)
    _app.include_router(_sator_router)
    _app.include_router(_strumenti_router)

    return _app


# ─── Avvio background ─────────────────────────────────────────────────────────

def start_form_server(port: int = FORM_PORT) -> None:
    """Avvia il form server in un thread daemon. Idempotente."""
    if _started.is_set():
        return
    _started.set()

    import asyncio
    import uvicorn

    fastapi_app = _build_fastapi_app()
    config = uvicorn.Config(
        fastapi_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(server.serve())
        except Exception as exc:
            logger.error("Form server terminato inaspettatamente: %s", exc)
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True, name="PortafoglioFormServer")
    t.start()
    logger.info("Form server avviato su http://127.0.0.1:%d/operazioni", port)
