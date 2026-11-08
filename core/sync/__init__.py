"""Sincronizzazione Desktop/Mobile, Fase 1: modalità ombra.

Solo calcoli in memoria: nessuna rete, nessuna scrittura, nessun task. Il flag `mobile_sync.enabled`
è spento di default e in questa fase nulla di runtime lo legge (nessun gancio nell'app).

Fase 2 (solo ambiente di prova): protocollo v2 a due messaggi (`v2`, `v2_client`, `v2_state`, `transport`), invio automatico
(`auto`), controllo all'avvio (`startup`), prezzi del Mobile in quarantena (`observations`) e configurazione personale
(`cloudflare_config`). La produzione è bloccata nel codice. Vedi ADR-0025."""
