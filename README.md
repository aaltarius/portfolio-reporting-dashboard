# Sestante — Portfolio Reporting Dashboard

Applicazione Python/Streamlit per il monitoraggio di un portafoglio titoli gestito su Fineco: quotazioni, posizioni, performance, rischio, benchmark, reportistica, confronto storico, pianificazione degli acquisti (SATOR) e ribilanciamento.

| Voce | Valore corrente |
| --- | --- |
| Versione applicativa (`APP_VERSION`, `persistence/storage.py`) | 5.7 |
| Ultima versione stabile taggata | `v5.0` (2026-09-08) |
| Schema dati | 3.4 |
| Repository | `aaltarius/portfolio-reporting-dashboard` (**pubblico**, verificato il 02/11/2026) |

Lo stato di dettaglio, le verifiche aperte e i limiti noti sono in [`docs/STATO.md`](docs/STATO.md); le attività aperte in [`docs/BACKLOG.md`](docs/BACKLOG.md).

## Avvio rapido

Requisito: Python 3.11 o successivo. Installazione delle dipendenze e avvio:

```
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

In alternativa si usa il launcher Windows `avvia_portafoglio.bat`. Il form-server operativo ascolta sulla porta 8502.

## Struttura del repository

| Percorso | Contenuto |
| --- | --- |
| `app.py` | punto di ingresso Streamlit |
| `core/` | formule finanziarie, servizi di dominio, cache, SATOR, benchmark (unica sede delle metriche) |
| `persistence/` | lettura, scrittura, normalizzazione, migrazione e backup dei dati |
| `ui/` | pagine, componenti, tema; `ui/charts/` builder Plotly; `ui/form_server/` operazioni scriventi esterne a Streamlit |
| `tools/` | strumenti di audit e diagnostica (es. `tools/cache_surface_audit.py`) |
| `tests/` | test locali, **non versionati** per scelta del proprietario (vedi ADR-0006) |
| `docs/` | documentazione di progetto (indice in [`docs/README.md`](docs/README.md)) |
| `data/`, `backups/` | dati runtime e backup: mai in un repository pubblico |

Prima di qualunque pubblicazione verificare l'assenza di credenziali, in particolare in `aggiorna_remoto.php` e `.streamlit/secrets.toml` (quest'ultimo ignorato da git; `.streamlit/config.toml` è invece versionato).

## Documentazione

| Documento | Funzione |
| --- | --- |
| [`CLAUDE.md`](CLAUDE.md) | istruzioni operative per l'agente AI che sviluppa sul repository |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | flusso di lavoro, definizione di completato, regole di aggiornamento della documentazione |
| [`CHANGELOG.md`](CHANGELOG.md) | modifiche per versione, in forma sintetica |
| [`docs/README.md`](docs/README.md) | mappa completa della documentazione |

## Sincronizzazione con il Mobile (facoltativa, spenta di default)

Il Desktop può inviare al Worker del Mobile i risultati già calcolati (posizioni, liquidità, storico, sedute): all'avvio controlla che il Mobile sia allineato e, dopo ogni salvataggio dei dati, invia in background solo le novità (circa 6 kB). Non partono operazioni, note né registro eventi. Per ora funziona **solo verso l'ambiente di prova**; la produzione è bloccata nel codice.

1. Eseguire `configura_sincronizzazione_mobile.bat`: chiede nomi, indirizzo e chiave del Worker, li salva in `data/segreti/cloudflare.json` (cartella ignorata da git) e prova il collegamento.
2. Accendere l'opzione **Setup → Aggiornamenti automatici in rete → Sincronizza con il Mobile**. La pastiglia «Mobile» nella barra in alto mostra lo stato (*off*, *controllo*, *allineato*, *invio*, *da verificare*, *offline*…); l'esito si legge anche in `data/logs/portafoglio.log`.

La chiave e la configurazione non vanno mai copiate fuori dal PC né pubblicate. Dettagli e decisioni: [ADR-0025](docs/adr/0025-protocollo-v2-bootstrap-e-update.md) (documentazione interna).

## Aggiornamento dal 5.4

L'aggiornamento diretto 5.4 → 5.6 è stato eseguito il 02/11/2026. La procedura storica (installer con `-DryRun`, ripristino dei sorgenti, gestione manuale degli storici) è conservata in [`docs/guide/benchmark-5.6-installazione-e-uso.md`](docs/guide/benchmark-5.6-installazione-e-uso.md). Il ripristino dei sorgenti non annulla le importazioni successive nell'archivio `data/indices/benchmarks.sqlite3`.
