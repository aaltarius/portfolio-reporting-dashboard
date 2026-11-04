# Contribuire a Sestante

Il progetto è sviluppato da un unico proprietario con il supporto di agenti AI. Le regole seguenti servono a mantenere il codice e la documentazione allineati tra una sessione e l'altra, quando chi riprende il lavoro non ha memoria di quella precedente.

## Flusso di lavoro

Ogni intervento parte da una voce di [`docs/BACKLOG.md`](docs/BACKLOG.md); se la voce non esiste, la si crea prima di iniziare. Gli interventi piccoli (correzione puntuale, rifinitura di interfaccia) procedono direttamente; gli interventi che toccano più moduli, il modello dati, la cache o il motore SATOR richiedono prima una specifica in `docs/superpowers/specs/` approvata dall'utente e poi un piano in `docs/superpowers/plans/`. Le decisioni architetturali emerse durante il lavoro si registrano come ADR in `docs/adr/`.

Il ramo di integrazione è `main`. Per lavori lunghi si usano worktree o rami dedicati, da rimuovere dopo il merge. I messaggi di commit sono in italiano, all'imperativo, con il riferimento alla voce di backlog quando esiste (es. `SATOR: deduplica candidati condivisi tra bucket (ST-07)`).

## Definizione di completato

Un intervento è completato quando sono soddisfatte tutte le condizioni seguenti: il comportamento richiesto è verificato sui dati reali o su una riproduzione fedele; esiste un test di regressione per ogni correzione di calcolo, dati, cache o navigazione; la suite locale è verde (`pytest tests/`, eseguita a blocchi come indicato in [`docs/sviluppo/test.md`](docs/sviluppo/test.md)); per interventi di prestazioni esistono misure prima/dopo secondo [`docs/architettura/performance.md`](docs/architettura/performance.md); la documentazione è aggiornata come indicato sotto; il lavoro è committato. Un intervento lasciato non committato si annota esplicitamente in `docs/STATO.md`, sezione «Lavori in sospeso».

## Dove va ogni informazione

| Informazione | Documento | Regola |
|---|---|---|
| Cosa è vero adesso (versioni, stato delle aree, limiti noti) | `docs/STATO.md` | si riscrive, non si accoda; massimo circa 200 righe |
| Cosa resta da fare | `docs/BACKLOG.md` | una riga per voce con ID stabile; le voci chiuse si spostano nella sezione «Chiuse di recente» e poi si eliminano |
| Cosa è cambiato per l'utente, per versione | `CHANGELOG.md` | formato Keep a Changelog, una riga per modifica |
| Come e perché si è arrivati a una modifica (diagnosi, cause, file, test) | `docs/diario/AAAA-MM.md` | si accoda in ordine di data, non si riscrive |
| Una decisione e le sue alternative | `docs/adr/NNNN-titolo.md` | immutabile dopo l'accettazione; si supera con un nuovo ADR |
| Come è fatto il sistema | `docs/architettura/` | si aggiorna quando cambia il codice |
| Come si lavora sul repository | `docs/sviluppo/` | convenzioni, test, rilascio, lezioni apprese |
| Progetto di una funzionalità | `docs/superpowers/specs/` e `plans/` | storici dopo l'implementazione; lo stato vive nell'indice |
| Materiale ricevuto da terzi | `docs/riferimenti/` | non si modifica; si cita |
| Documenti superati | `docs/archivio/` | sola lettura |

Il principio è che ogni informazione abbia una sola sede. Se un documento deve citare un fatto che vive altrove, lo richiama con un collegamento invece di ripeterlo.

## Riservatezza prima di ogni commit e di ogni invio

Il repository GitHub è pubblico: nessun dato personale dell'utente deve entrarvi ([ADR-0020](docs/adr/0020-riservatezza-dei-dati-personali.md)). Prima di ogni commit si controlla `git status` e `git diff --cached --stat`: non devono comparire file di `data/`, `backups/`, `docs/`, `tests/` o rapporti generati dall'app, né importi, quantità o ticker reali in commenti, CHANGELOG, test e fixture. Il `git push` non lo esegue mai l'agente di propria iniziativa: lo decide l'utente, dopo aver visto `git diff --stat origin/main..HEAD`.

## Versioni

`APP_VERSION` in `persistence/storage.py` identifica la versione dell'applicazione e partecipa alla firma delle cache di pagina: cambiarla invalida gli artefatti cacheati. Si incrementa la cifra minore a ogni rilascio che modifica calcoli, grafici cacheati o comportamento visibile; si crea un tag git `vX.Y` per le versioni dichiarate stabili. La numerazione è unica ([ADR-0015](docs/adr/0015-numerazione-unica-delle-versioni.md)): i pacchetti di aggiornamento portano il numero della versione applicativa. La procedura di rilascio è in [`docs/sviluppo/rilascio.md`](docs/sviluppo/rilascio.md).

## Convenzioni dei file di documentazione

I nomi di file sono in minuscolo, in kebab-case e senza caratteri non ASCII (un file con trattino tipografico nel nome si è già corrotto in un archivio ZIP). Le date nei nomi seguono il formato `AAAA-MM-GG`. I documenti sono in Markdown con un solo titolo di primo livello. Fanno eccezione i file convenzionali in maiuscolo (`README.md`, `CHANGELOG.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `STATO.md`, `BACKLOG.md`) e i file dei pacchetti esterni in `docs/riferimenti/`, che mantengono i nomi originali.
