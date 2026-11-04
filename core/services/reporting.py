"""
core/services/reporting.py — Reporting and compliance services.

Functions for building compliance packs and rendering reports.
Pure functions - no Streamlit dependencies, no side effects.
"""
import hashlib
import json
from datetime import datetime
from typing import Any
from datetime import date
import pandas as pd


def build_reporting_compliance_pack(
    summary_payload: dict[str, Any],
    settings: dict[str, Any] | None,
    meta_state: dict[str, Any] | None,
    *,
    app_version: str,
    schema_version: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Costruisce un record di reporting tracciabile per uso interno."""
    settings = settings if isinstance(settings, dict) else {}
    meta_state = meta_state if isinstance(meta_state, dict) else {}
    reporting_settings = settings.get("reporting_export", {}) if isinstance(settings.get("reporting_export", {}), dict) else {}
    audit_state = meta_state.get("audit", {}) if isinstance(meta_state.get("audit", {}), dict) else {}
    audit_events = audit_state.get("events", []) if isinstance(audit_state.get("events", []), list) else []
    runtime_state = meta_state.get("runtime", {}) if isinstance(meta_state.get("runtime", {}), dict) else {}
    migration_state = meta_state.get("migration", {}) if isinstance(meta_state.get("migration", {}), dict) else {}
    generated_at = generated_at or datetime.now()
    payload_digest = hashlib.md5(
        json.dumps(summary_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]

    recent_events = [
        {
            "timestamp": item.get("timestamp"),
            "event_type": item.get("event_type"),
            "category": item.get("category"),
            "status": item.get("status"),
        }
        for item in audit_events[-5:]
    ]

    return {
        "record_type": "portfolio_reporting_pack",
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        "payload_digest": payload_digest,
        "app": {
            "name": "Sestante",
            "version": app_version,
            "schema_version": schema_version,
        },
        "portfolio": {
            "portfolio_id": summary_payload.get("portfolio_id"),
            "portfolio_name": summary_payload.get("portfolio_name"),
            "base_currency": summary_payload.get("base_currency"),
            "reporting_currency": summary_payload.get("reporting_currency"),
            "valuation_timestamp": summary_payload.get("valuation_timestamp"),
        },
        "benchmark": {
            "label": summary_payload.get("portfolio_benchmark"),
            "is_custom": bool(summary_payload.get("portfolio_benchmark_is_custom", False)),
            "components": summary_payload.get("portfolio_benchmark_components", []),
        },
        "methodology": summary_payload.get("methodology", {}),
        "reporting_preferences": {
            "default_format": reporting_settings.get("default_format"),
            "decimal_places": reporting_settings.get("decimal_places"),
            "include_history": reporting_settings.get("include_history"),
            "include_methodology": reporting_settings.get("include_methodology"),
            "include_holdings_table": reporting_settings.get("include_holdings_table"),
            "include_benchmark": reporting_settings.get("include_benchmark"),
        },
        "i18n": settings.get("i18n", {}),
        "runtime": {
            "last_start": runtime_state.get("last_start"),
            "last_successful_save": runtime_state.get("last_successful_save"),
            "last_migration": migration_state.get("migration_timestamp"),
        },
        "audit": {
            "enabled": bool(settings.get("auditing", {}).get("enabled", True)),
            "total_events": len(audit_events),
            "last_event_timestamp": audit_events[-1].get("timestamp") if audit_events else None,
            "recent_events": recent_events,
        },
        "summary_snapshot": {
            "total_market_value": summary_payload.get("total_market_value"),
            "total_pl": summary_payload.get("total_pl"),
            "total_pl_pct": summary_payload.get("total_pl_pct"),
            "xirr": summary_payload.get("xirr"),
            "xirr_scope": summary_payload.get("xirr_scope"),
            "xirr_assets": summary_payload.get("xirr_assets"),
            "xirr_portfolio": summary_payload.get("xirr_portfolio"),
            "twr": summary_payload.get("twr"),
            "volatility_ann": summary_payload.get("volatility_ann"),
            "max_drawdown": summary_payload.get("max_drawdown"),
        },
        "compliance_note": summary_payload.get("compliance_note"),
    }


def _fmt_xirr_scope(scope: Any) -> str:
    if scope == "portfolio_external":
        return "Portafoglio: flussi esterni + patrimonio finale"
    if scope == "invested_assets":
        return "Strumenti investiti: fallback senza flussi esterni completi"
    return "n/d"


def render_reporting_compliance_markdown(reporting_pack: dict[str, Any]) -> str:
    """Rende il reporting pack in forma markdown sintetica e leggibile."""
    app = reporting_pack.get("app", {}) if isinstance(reporting_pack.get("app", {}), dict) else {}
    portfolio = reporting_pack.get("portfolio", {}) if isinstance(reporting_pack.get("portfolio", {}), dict) else {}
    benchmark = reporting_pack.get("benchmark", {}) if isinstance(reporting_pack.get("benchmark", {}), dict) else {}
    i18n = reporting_pack.get("i18n", {}) if isinstance(reporting_pack.get("i18n", {}), dict) else {}
    runtime = reporting_pack.get("runtime", {}) if isinstance(reporting_pack.get("runtime", {}), dict) else {}
    audit = reporting_pack.get("audit", {}) if isinstance(reporting_pack.get("audit", {}), dict) else {}
    snapshot = reporting_pack.get("summary_snapshot", {}) if isinstance(reporting_pack.get("summary_snapshot", {}), dict) else {}
    methodology = reporting_pack.get("methodology", {}) if isinstance(reporting_pack.get("methodology", {}), dict) else {}
    recent_events = audit.get("recent_events", []) if isinstance(audit.get("recent_events", []), list) else []
    date_format = str(i18n.get("date_format", "DD/MM/YYYY"))
    number_format = str(i18n.get("number_format", i18n.get("locale", "it-IT")))

    def _fmt_num(value: Any, decimals: int = 2, percent: bool = False) -> str:
        try:
            if value is None:
                return "n/d"
            val = float(value)
        except Exception:
            return "n/d"
        if percent:
            val *= 100.0
        if number_format == "en-US":
            rendered = f"{val:,.{decimals}f}"
        else:
            rendered = f"{val:,.{decimals}f}".replace(",", "§").replace(".", ",").replace("§", ".")
        return f"{rendered}%" if percent else rendered

    def _fmt_date(value: Any) -> str:
        if value in (None, ""):
            return "n/d"
        parsed = None
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value)
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(text[:19], fmt)
                    break
                except Exception:
                    continue
        if parsed is None:
            return str(value)
        if date_format == "MM/DD/YYYY":
            return f"{parsed.month:02d}/{parsed.day:02d}/{parsed.year} {parsed.hour:02d}:{parsed.minute:02d}"
        return f"{parsed.day:02d}/{parsed.month:02d}/{parsed.year} {parsed.hour:02d}:{parsed.minute:02d}"

    lines = [
        "# Reporting Compliance Pack",
        "",
        f"- Generato il: {_fmt_date(reporting_pack.get('generated_at', 'n/d'))}",
        f"- Record digest: {reporting_pack.get('payload_digest', 'n/d')}",
        f"- Applicazione: {app.get('name', 'n/d')} v{app.get('version', 'n/d')} (schema {app.get('schema_version', 'n/d')})",
        "",
        "## Portafoglio",
        f"- ID: {portfolio.get('portfolio_id', 'n/d')}",
        f"- Nome: {portfolio.get('portfolio_name', 'n/d')}",
        f"- Valuta base: {portfolio.get('base_currency', 'n/d')}",
        f"- Valuta reporting: {portfolio.get('reporting_currency', 'n/d')}",
        f"- Data valutazione: {_fmt_date(portfolio.get('valuation_timestamp', 'n/d'))}",
        "",
        "## Benchmark e metodologia",
        f"- Benchmark: {benchmark.get('label', 'n/d')}",
        f"- Benchmark personalizzato: {'Sì' if benchmark.get('is_custom') else 'No'}",
        f"- Lingua report: {i18n.get('language', 'n/d')}",
        f"- Locale report: {i18n.get('locale', 'n/d')}",
        f"- Regola di valorizzazione: {methodology.get('valuation_rule', 'n/d')}",
        f"- Money-weighted return: {methodology.get('money_weighted_return', 'n/d')}",
        f"- Time-weighted proxy: {methodology.get('time_weighted_proxy', 'n/d')}",
        "",
        "## Snapshot sintetico",
        f"- Valore di mercato: {_fmt_num(snapshot.get('total_market_value'), 2)}",
        f"- P/L totale: {_fmt_num(snapshot.get('total_pl'), 2)}",
        f"- P/L %: {_fmt_num(snapshot.get('total_pl_pct'), 2, percent=True)}",
        f"- XIRR: {_fmt_num(snapshot.get('xirr'), 2, percent=True)}",
        f"- Origine XIRR: {_fmt_xirr_scope(snapshot.get('xirr_scope'))}",
        f"- XIRR strumenti: {_fmt_num(snapshot.get('xirr_assets'), 2, percent=True)}",
        f"- TWR proxy: {_fmt_num(snapshot.get('twr'), 2, percent=True)}",
        f"- Volatilità annua: {_fmt_num(snapshot.get('volatility_ann'), 2, percent=True)}",
        f"- Max drawdown: {_fmt_num(snapshot.get('max_drawdown'), 2, percent=True)}",
        "",
        "## Runtime e audit",
        f"- Ultimo avvio: {_fmt_date(runtime.get('last_start', 'n/d'))}",
        f"- Ultimo salvataggio riuscito: {_fmt_date(runtime.get('last_successful_save', 'n/d'))}",
        f"- Ultima migrazione: {_fmt_date(runtime.get('last_migration', 'n/d'))}",
        f"- Audit attivo: {'Sì' if audit.get('enabled') else 'No'}",
        f"- Eventi audit registrati: {audit.get('total_events', 0)}",
        f"- Ultimo evento audit: {_fmt_date(audit.get('last_event_timestamp', 'n/d'))}",
        "",
        "## Eventi recenti",
    ]
    if recent_events:
        for item in recent_events:
            lines.append(
                f"- {_fmt_date(item.get('timestamp', 'n/d'))} | {item.get('category', 'n/d')} | {item.get('event_type', 'n/d')} | {item.get('status', 'n/d')}"
            )
    else:
        lines.append("- Nessun evento recente disponibile")
    lines.extend([
        "",
        "## Nota",
        str(reporting_pack.get("compliance_note", "n/d")),
    ])
    return "\n".join(lines)
