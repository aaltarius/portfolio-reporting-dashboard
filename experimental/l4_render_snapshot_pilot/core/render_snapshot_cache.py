from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.cache_policy import build_cache_artifact_signature
from core.page_cache import get_or_build_page_artifact
from core.render_profiler import record_render_event
from core.render_snapshot_policy import get_render_snapshot_spec


RENDER_SNAPSHOT_SCHEMA = "render-snapshot-v1"


@dataclass(frozen=True)
class RenderSnapshot:
    artifact_id: str
    signature: str
    source: str
    html: str
    height: int | str
    meta: dict[str, Any]


def _normalize_snapshot_payload(value: Any, *, default_height: int | str) -> dict[str, Any]:
    if isinstance(value, dict):
        html = str(value.get("html") or "")
        height = value.get("height", default_height)
        meta = value.get("meta") if isinstance(value.get("meta"), dict) else {}
    else:
        html = str(value or "")
        height = default_height
        meta = {}
    return {
        "schema": RENDER_SNAPSHOT_SCHEMA,
        "html": html,
        "height": height,
        "meta": meta,
    }


def get_or_build_render_snapshot(
    artifact_id: str,
    *,
    inputs: dict[str, Any],
    builder: Callable[[], dict[str, Any]],
    default_height: int | str = "content",
    persist_disk: bool = True,
) -> RenderSnapshot:
    """Cache ufficiale L4 per snapshot HTML read-only."""

    spec = get_render_snapshot_spec(artifact_id)
    signature = build_cache_artifact_signature(artifact_id, inputs=inputs)

    def _build_payload() -> dict[str, Any]:
        return _normalize_snapshot_payload(builder(), default_height=default_height)

    artifact = get_or_build_page_artifact(
        page_id=spec.page_id,
        layer=spec.layer,
        signature=signature,
        builder=_build_payload,
        profile_page=spec.log_page,
        clone_on_read=False,
        persist_disk=persist_disk,
    )
    payload = _normalize_snapshot_payload(artifact.value, default_height=default_height)
    html = str(payload.get("html") or "")
    height = payload.get("height", default_height)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    try:
        record_render_event(
            spec.log_page,
            f"L4 render snapshot {spec.layer}",
            0.0,
            detail=f"source={artifact.source}; sig={signature}; bytes={len(html.encode('utf-8'))}",
        )
    except Exception:
        pass
    return RenderSnapshot(
        artifact_id=artifact_id,
        signature=signature,
        source=artifact.source,
        html=html,
        height=height,
        meta=meta,
    )
