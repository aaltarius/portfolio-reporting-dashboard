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
import time
from typing import Any

logger = logging.getLogger("portafoglio.form_server")

FORM_PORT = 8502

_started = threading.Event()
_start_lock = threading.Lock()
_server_thread: threading.Thread | None = None
_last_error: str | None = None


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
    global _server_thread, _last_error

    with _start_lock:
        if _server_thread is not None and _server_thread.is_alive():
            _started.set()
            return

        if _started.is_set():
            logger.warning(
                "Form server marcato come avviato, ma il thread non risponde: nuovo tentativo su porta %d",
                port,
            )
            _started.clear()

        try:
            import asyncio
            import uvicorn

            fastapi_app = _build_fastapi_app()
        except Exception as exc:
            _last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Impossibile preparare il form server su porta %d: %s", port, _last_error)
            _started.clear()
            return

        config = uvicorn.Config(
            fastapi_app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)

        def _run():
            global _last_error
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(server.serve())
            except Exception as exc:
                _last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Form server terminato inaspettatamente: %s", _last_error)
            finally:
                _started.clear()
                loop.close()

        _server_thread = threading.Thread(target=_run, daemon=True, name="PortafoglioFormServer")
        _server_thread.start()
        _started.set()

        for _ in range(20):
            if getattr(server, "started", False):
                _last_error = None
                logger.info("Form server attivo su http://127.0.0.1:%d/operazioni", port)
                return
            if not _server_thread.is_alive():
                _started.clear()
                _last_error = _last_error or "Il thread Uvicorn si e' chiuso prima dell'avvio."
                logger.error("Form server non avviato su porta %d: %s", port, _last_error)
                return
            time.sleep(0.05)

        logger.info("Form server in avvio su http://127.0.0.1:%d/operazioni", port)


def get_form_server_status() -> dict[str, Any]:
    """Restituisce uno stato leggero per diagnostica UI/log."""
    return {
        "port": FORM_PORT,
        "started": _started.is_set(),
        "thread_alive": bool(_server_thread is not None and _server_thread.is_alive()),
        "last_error": _last_error,
    }
