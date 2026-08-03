from __future__ import annotations

from core.cache_policy import CacheArtifactSpec, get_cache_artifact_spec


RENDER_SNAPSHOT_ARTIFACT_IDS = {
    "cruscotti.category_render_snapshot",
}


def get_render_snapshot_spec(artifact_id: str) -> CacheArtifactSpec:
    """Restituisce una spec cache ammessa come snapshot L4."""

    spec = get_cache_artifact_spec(artifact_id)
    if spec.artifact_id not in RENDER_SNAPSHOT_ARTIFACT_IDS or spec.level != "L4":
        raise KeyError(f"Render snapshot non registrato: {artifact_id}")
    return spec
