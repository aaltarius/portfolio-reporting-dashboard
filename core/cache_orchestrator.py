from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.cache_policy import CacheArtifactSpec, get_cache_artifact_spec
from core.page_cache import PageArtifact, get_or_build_page_artifact


PAGE_ARTIFACT_STORAGES = {
    "page_artifact",
    "page_artifact_plus_figure_cache",
    "report_archive_plus_page_artifact",
}


@dataclass(frozen=True)
class CacheProviderContract:
    """Contratto operativo di un provider cache ammesso dall'orchestrazione."""

    artifact_id: str
    provider: str
    storage: str
    page_id: str
    layer: str
    clear_group: str
    trigger: str
    rerun_policy: str
    action_scope: str


def build_provider_contract(artifact_id: str) -> CacheProviderContract:
    """Restituisce il contratto provider derivato dal registry centrale."""

    spec = get_cache_artifact_spec(artifact_id)
    return CacheProviderContract(
        artifact_id=spec.artifact_id,
        provider=_provider_for_spec(spec),
        storage=spec.storage,
        page_id=spec.page_id,
        layer=spec.layer,
        clear_group=spec.clear_group,
        trigger=spec.trigger,
        rerun_policy=spec.rerun_policy,
        action_scope=spec.action_scope,
    )


def get_or_build_registered_artifact(
    *,
    artifact_id: str,
    signature: str,
    builder: Callable[[], Any],
    clone_on_read: bool = False,
    persist_disk: bool | None = None,
    disk_codec: str = "gzip",
) -> PageArtifact:
    """Ingresso canonico per gli artefatti page-cache registrati.

    Le pagine e i servizi passano solo `artifact_id`, firma e builder. Il
    mapping page/layer/log/storage arriva dal registry: in questo modo la
    policy non viene ricostruita localmente in ogni modulo.
    """

    spec = get_cache_artifact_spec(artifact_id)
    if spec.storage not in PAGE_ARTIFACT_STORAGES:
        raise ValueError(
            f"Artifact {artifact_id!r} usa storage {spec.storage!r}: "
            "non e' un page artifact gestibile da get_or_build_registered_artifact"
        )
    return get_or_build_page_artifact(
        page_id=spec.page_id,
        layer=spec.layer,
        signature=str(signature or "no-signature"),
        builder=builder,
        profile_page=spec.log_page,
        clone_on_read=clone_on_read,
        persist_disk=True if persist_disk is None else bool(persist_disk),
        disk_codec=disk_codec,
    )


class RegisteredFigureCacheAdapter:
    """Adapter registry-aware per il provider Plotly FigureCache.

    Mantiene la stessa API `get_or_build` della FigureCache esistente, ma ogni
    accesso viene autorizzato dal registry tramite `figures.plotly_cache_provider`.
    Le altre API diagnostiche/manutentive vengono delegate al provider reale.
    """

    artifact_id = "figures.plotly_cache_provider"

    def __init__(self, artifact_id: str = "figures.plotly_cache_provider") -> None:
        self.artifact_id = str(artifact_id or "figures.plotly_cache_provider")

    def get_or_build(
        self,
        *,
        chart_id: str,
        data_sig: str,
        theme_sig: str,
        charts_settings_sig: str,
        builder: Callable[[], Any],
        page_mode: str | None = None,
        extra_params: dict[str, Any] | None = None,
        strategy: str = "hybrid",
        record_event: bool = True,
    ) -> Any:
        return get_or_build_registered_figure(
            artifact_id=self.artifact_id,
            chart_id=chart_id,
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_settings_sig,
            builder=builder,
            page_mode=page_mode,
            extra_params=extra_params,
            strategy=strategy,
            record_event=record_event,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(_get_raw_figure_cache(), name)


_REGISTERED_FIGURE_CACHE_ADAPTERS: dict[str, RegisteredFigureCacheAdapter] = {}


def get_registered_figure_cache(
    artifact_id: str = "figures.plotly_cache_provider",
) -> RegisteredFigureCacheAdapter:
    """Restituisce l'adapter ufficiale per le figure Plotly registrate."""

    artifact_id = str(artifact_id or "figures.plotly_cache_provider").strip()
    spec = get_cache_artifact_spec(artifact_id)
    if _provider_for_spec(spec) != "core.figure_cache":
        raise ValueError(f"Artifact {artifact_id!r} non e' un provider FigureCache")
    adapter = _REGISTERED_FIGURE_CACHE_ADAPTERS.get(artifact_id)
    if adapter is None:
        adapter = RegisteredFigureCacheAdapter(artifact_id)
        _REGISTERED_FIGURE_CACHE_ADAPTERS[artifact_id] = adapter
    return adapter


def get_or_build_registered_figure(
    *,
    artifact_id: str = "figures.plotly_cache_provider",
    chart_id: str,
    data_sig: str,
    theme_sig: str,
    charts_settings_sig: str,
    builder: Callable[[], Any],
    page_mode: str | None = None,
    extra_params: dict[str, Any] | None = None,
    strategy: str = "hybrid",
    record_event: bool = True,
) -> Any:
    """Ingresso canonico per le figure Plotly cacheate.

    FigureCache resta lo store specializzato, ma non e' piu' il contratto
    architetturale consumato da pagine e servizi.
    """

    spec = get_cache_artifact_spec(artifact_id)
    if _provider_for_spec(spec) != "core.figure_cache":
        raise ValueError(f"Artifact {artifact_id!r} usa storage {spec.storage!r}, non FigureCache")
    return _get_raw_figure_cache().get_or_build(
        chart_id=chart_id,
        data_sig=data_sig,
        theme_sig=theme_sig,
        charts_settings_sig=charts_settings_sig,
        builder=builder,
        page_mode=page_mode,
        extra_params=extra_params,
        strategy=strategy,
        record_event=record_event,
    )


def load_registered_analytics_entry(
    *,
    artifact_id: str = "analytics.frozen_payload_store",
    payload_type: str,
    signature: str,
) -> tuple[dict[str, Any] | None, bool, str]:
    """Carica un payload analitico persistente tramite provider registrato."""

    spec = get_cache_artifact_spec(artifact_id)
    if _provider_for_spec(spec) != "core.analytics_payload_cache":
        raise ValueError(f"Artifact {artifact_id!r} usa storage {spec.storage!r}, non analytics payload cache")
    from core.analytics_payload_cache import load_entry

    return load_entry(payload_type, signature)


def store_registered_analytics_entry(
    *,
    artifact_id: str = "analytics.frozen_payload_store",
    payload_type: str,
    signature: str,
    entry: dict[str, Any],
    max_entries: int = 6,
) -> None:
    """Salva un payload analitico persistente tramite provider registrato."""

    spec = get_cache_artifact_spec(artifact_id)
    if _provider_for_spec(spec) != "core.analytics_payload_cache":
        raise ValueError(f"Artifact {artifact_id!r} usa storage {spec.storage!r}, non analytics payload cache")
    from core.analytics_payload_cache import store_entry

    store_entry(payload_type, signature, entry, max_entries=max_entries)


def get_registered_runtime_cache(
    artifact_id: str,
    *,
    namespace: str = "default",
    max_entries: int = 0,
) -> Any:
    """Restituisce una cache runtime tramite il contratto orchestrato."""

    spec = get_cache_artifact_spec(artifact_id)
    if _provider_for_spec(spec) != "core.runtime_cache":
        raise ValueError(f"Artifact {artifact_id!r} usa storage {spec.storage!r}, non runtime cache")
    from core.runtime_cache import get_runtime_cache

    return get_runtime_cache(artifact_id, namespace=namespace, max_entries=max_entries)


def clear_registered_runtime_caches(*, clear_group: str | None = None) -> int:
    """Pulisce cache runtime registrate attraverso l'orchestratore."""

    from core.runtime_cache import clear_runtime_caches

    return clear_runtime_caches(clear_group=clear_group)


def iter_registered_runtime_cache_stats() -> tuple[Any, ...]:
    """Statistiche runtime-cache esposte dal livello orchestratore."""

    from core.runtime_cache import iter_runtime_cache_stats

    return iter_runtime_cache_stats()


def _get_raw_figure_cache() -> Any:
    from core.figure_cache import get_figure_cache

    return get_figure_cache()


def _provider_for_spec(spec: CacheArtifactSpec) -> str:
    storage = str(spec.storage or "").strip()
    if storage in PAGE_ARTIFACT_STORAGES:
        return "core.page_cache"
    if storage in {"process_memory_lru", "runtime_memory_plus_cache_file", "derived_runtime_pickle"}:
        return "core.runtime_cache"
    if storage in {"figure_cache", "figure_cache_manifest_json_gzip"}:
        return "core.figure_cache"
    if storage in {"analytics_payload_cache", "analytics_pickle_gzip"}:
        return "core.analytics_payload_cache"
    if storage == "streamlit_resource":
        return "streamlit.cache_resource"
    return storage or "unknown"
