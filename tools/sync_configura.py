"""Configurazione guidata della sincronizzazione Mobile: crea o corregge `data/segreti/cloudflare.json`.

  python -m tools.sync_configura           procedura guidata (una domanda alla volta, con valori già pronti)
  python -m tools.sync_configura --verifica   controlla il file esistente e prova il collegamento, senza cambiare nulla

Cosa fa: chiede indirizzo, nomi e intervalli, compone da solo l'indirizzo completo, controlla che i nomi siano validi,
salva la chiave in un file a parte (digitata senza che compaia sullo schermo), tiene una copia del file precedente,
verifica che la cartella sia ignorata da git e prova il collegamento al Worker di prova. La produzione resta bloccata."""
from __future__ import annotations

import getpass
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULTS = {"worker": "sestante-mobile-prova", "bucket": "sestante-prova", "binding_r2": "SESTANTE_R2"}
_LABEL = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")
_HINTS = {
    "HTTP 401": "La chiave (SYNC_TOKEN) non è accettata dal Worker: controlla che sia quella del Worker di prova.",
    "HTTP 403": "Il Worker rifiuta l'accesso: nel Worker di prova manca la variabile V2_TEST_ONLY=1, oppure l'indirizzo non inizia con «sestante-mobile-prova».",
    "HTTP 404": "Il Worker risponde ma non conosce il protocollo v2: va pubblicato il codice della versione 1.5.",
    "HTTP 503": "Il Worker è raggiungibile ma mancano i suoi segreti o il collegamento al bucket (binding SESTANTE_R2).",
}


def _example() -> dict:
    import copy
    from core.sync.cloudflare_config import EXAMPLE_CONFIG
    return copy.deepcopy(EXAMPLE_CONFIG)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def compose_url(worker: str, subdomain: str) -> str:
    worker, subdomain = worker.strip().lower(), subdomain.strip().lower()
    if not _LABEL.match(worker) or not _LABEL.match(subdomain):
        raise ValueError("nome del Worker o parte dell'account non validi (solo lettere minuscole, numeri e trattini)")
    return f"https://{worker}.{subdomain}.workers.dev"


def split_url(url: str) -> tuple[str, str]:
    m = re.match(r"^https://([a-z0-9-]+)\.([a-z0-9-]+)\.workers\.dev/?$", str(url or ""))
    return (m.group(1), m.group(2)) if m else ("", "")


def apply_answers(cfg: dict, *, env: str, worker: str, subdomain: str, bucket: str, binding: str,
                  token_file: str, min_interval_s: int, btp_days: int, gzip: bool) -> dict:
    """Restituisce una copia della configurazione con i valori dati (solo l'ambiente indicato; la produzione non si tocca)."""
    import copy
    new = copy.deepcopy(cfg)
    e = new["ambienti"].setdefault(env, {})
    e.update(invio_consentito=True, url=compose_url(worker, subdomain), worker=worker.strip(), bucket=bucket.strip(),
             binding_r2=binding.strip(), sync_token_file=token_file, sync_token="")
    new.setdefault("invio", {}).update(min_intervallo_s=int(min_interval_s), btp_giorni_recenti=int(btp_days), gzip=bool(gzip))
    return new


def validate(cfg: dict, env: str = "prova") -> list[str]:
    """Elenco dei problemi (vuoto se il file è utilizzabile)."""
    import tempfile
    from core.sync import cloudflare_config as cc
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "c.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        try:
            loaded = cc.load_config(p)
            cc.get_environment(loaded, env, config_path=p)
        except cc.ConfigError as exc:
            problems.append(str(exc))
    return problems


def gitignored(path: Path) -> bool | None:
    repo = Path(__file__).resolve().parent.parent
    try:
        return subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=repo, capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def check_connection(cfg_path: Path, env_name: str = "prova", transport_factory=None) -> tuple[bool, str]:
    from core.sync import cloudflare_config as cc
    from core.sync.transport import HttpTransport
    try:
        cfg = cc.load_config(cfg_path)
        env = cc.get_environment(cfg, env_name, config_path=cfg_path)
        token = env.token
    except cc.ConfigError as exc:
        return False, str(exc)
    transport = transport_factory(env, token) if transport_factory else HttpTransport(
        env.url, token, allowed_hosts={env.host}, timeout=env.timeout_s, user_agent=env.user_agent)
    try:
        state = transport.get_json(env.endpoints["v2_state"])
    except RuntimeError as exc:
        text = str(exc)
        return False, _HINTS.get(text, "Il Worker non è raggiungibile: controlla l'indirizzo e la connessione." if "raggiungibile" in text else text)
    base = (f"Collegamento riuscito. Il Mobile ha già dati (invio n. {state.get('seq')})." if state.get("bootstrapped")
            else "Collegamento riuscito. Il Mobile non ha ancora dati: il primo invio partirà da solo.")
    from core.sync import observations as obs
    found = obs.fetch(transport, env.endpoints.get("v2_observations", obs.ENDPOINT))
    if found is None:
        return True, base + " Prezzi del Mobile: non disponibili (serve il Worker 1.5.1 o successivo)."
    return True, base + f" Prezzi del Mobile: disponibili ({len(found)})."


def main(argv=None, *, ask=input, ask_secret=getpass.getpass, out=print, root: Path | None = None, transport_factory=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(root) if root else Path(__file__).resolve().parent.parent / "data" / "segreti"
    cfg_path = root / "cloudflare.json"
    if "--verifica" in args:
        ok, msg = check_connection(cfg_path, transport_factory=transport_factory)
        out(("OK: " if ok else "PROBLEMA: ") + msg)
        return 0 if ok else 2

    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else _example()
    cur = cfg.get("ambienti", {}).get("prova", {})
    cur_w, cur_sub = split_url(cur.get("url", ""))
    real = lambda v: "" if (not v or str(v).isupper()) else v      # i segnaposto del modello (NOME-…) non sono valori veri

    def q(text, default=""):
        a = ask(f"{text}" + (f" [{default}]" if default else "") + ": ").strip()
        return a or default

    out("Configurazione guidata della sincronizzazione Mobile (ambiente di PROVA). Premi Invio per tenere il valore proposto.\n")
    out("L'indirizzo del Worker ha la forma  https://NOME-WORKER.TUO-ACCOUNT.workers.dev  (lo trovi in cima alla pagina del Worker).")
    worker = q("Nome del Worker", real(cur.get("worker")) or DEFAULTS["worker"])
    subdomain = q("Parte dell'account nell'indirizzo (quella tra il nome del Worker e «workers.dev»)", cur_sub)
    bucket = q("Nome del bucket R2 di prova", real(cur.get("bucket")) or DEFAULTS["bucket"])
    binding = q("Nome del collegamento al bucket", cur.get("binding_r2") or DEFAULTS["binding_r2"])
    inv = cfg.get("invio", {})
    interval = q("Secondi minimi tra due invii di soli prezzi", str(inv.get("min_intervallo_s", 300)))
    btp_days = q("Giorni recenti dei BTP da rinviare", str(inv.get("btp_giorni_recenti", 10)))
    gz = q("Comprimere gli invii? (s/n)", "s" if inv.get("gzip", True) else "n").lower().startswith("s")
    token_name = "token_prova.txt"
    token_path = root / token_name
    keep = token_path.exists() and q("Esiste già una chiave salvata. Tenerla? (s/n)", "s").lower().startswith("s")
    secret = ""
    if not keep:
        out("Incolla la chiave SYNC_TOKEN del Worker di prova (non comparirà sullo schermo). Non è la password di Cloudflare.")
        secret = ask_secret("Chiave: ").strip()
        if len(secret) < 32:
            out("PROBLEMA: la chiave è troppo corta (servono almeno 32 caratteri). Nulla è stato modificato.")
            return 2
    try:
        for label, value in (("secondi tra due invii", interval), ("giorni dei BTP", btp_days)):
            if not value.isdigit():
                raise ValueError(f"«{label}» deve essere un numero intero (hai scritto «{value}»)")
        new = apply_answers(cfg, env="prova", worker=worker, subdomain=subdomain, bucket=bucket, binding=binding,
                            token_file=token_name, min_interval_s=int(interval), btp_days=int(btp_days), gzip=gz)
    except ValueError as exc:
        out(f"PROBLEMA: {exc}. Nulla è stato modificato.")
        return 2
    problems = validate(new)
    if problems:
        out("PROBLEMA: " + "; ".join(problems) + ". Nulla è stato modificato.")
        return 2
    if cfg_path.exists():
        _atomic_write(cfg_path.with_name("cloudflare.json.bak"), cfg_path.read_text(encoding="utf-8"))
    _atomic_write(cfg_path, json.dumps(new, ensure_ascii=False, indent=2))
    if secret:
        _atomic_write(token_path, secret + "\n")
    out(f"\nSalvato: {cfg_path}")
    ign = gitignored(cfg_path)
    out("Cartella protetta da git: " + ("sì" if ign else "ATTENZIONE, non risulta ignorata da git: non copiare questi file online" if ign is False else "non verificabile"))
    ok, msg = check_connection(cfg_path, transport_factory=transport_factory)
    out(("Prova di collegamento: OK. " if ok else "Prova di collegamento: PROBLEMA. ") + msg)
    out("L'ambiente di produzione resta bloccato.")
    if ok and q("Accendere l'invio automatico verso il Mobile di prova? (s/n)", "n").lower().startswith("s"):
        from tools import sync_v2_switch
        sync_v2_switch.main(["on"])
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
