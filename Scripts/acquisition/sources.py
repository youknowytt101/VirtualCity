"""Declarative source registry — the single source of truth for data acquisition.

This module centralises the three things that previously drifted across
``data_cleaning_cache`` (cache fingerprint), ``set_area`` (fallback execution)
and ``app/area_picker/server`` (UI metadata):

  * the *profile label* baked into every cache manifest / ``active_area.json``;
  * the *fallback chain* (which provider is tried, in what order);
  * the *display metadata* shown to the operator.

Swapping in a higher-precision / higher-accuracy API later should mean editing
*one* ``SourceSpec`` here — not hunting through the pipeline.

CONTRACT (do not break without bumping cache schema):
  ``acquisition_profile()`` must reproduce the historical
  ``CURRENT_ACQUISITION_PROFILE`` dict *byte-for-byte* once serialised by
  ``data_cleaning_cache.stable_json``.  Any change to the ``profile`` strings or
  ``schema`` below invalidates every stored clip/clean cache and forces a full
  re-download.  The fallback ``order`` and display fields are presentation /
  routing only and never enter the fingerprint.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Pinned cache-profile schema. Bumping this is a deliberate cache-invalidation
# event; it is intentionally separate from the per-source recipe versions.
PROFILE_SCHEMA = 1


@dataclass(frozen=True)
class SourceSpec:
    """One acquisition group (roads / buildings / dem).

    ``profile`` is the fingerprint label and MUST stay stable across refactors.
    ``order`` documents the runtime fallback chain (cache → local tile → remote)
    in human terms; it routes nothing on its own today but is the place a new
    high-precision provider gets inserted.  ``provider`` / ``method`` /
    ``strategy_label`` feed the operator-facing UI verbatim.
    """

    key: str
    title: str
    profile: str
    provider: str
    method: str
    strategy_label: str
    order: tuple[str, ...] = field(default_factory=tuple)


# ── The registry ─────────────────────────────────────────────────────────────
# Ordering of entries here defines the canonical group order. The literal
# ``profile`` strings below are frozen by ``tests/test_acquisition_sources.py``.
SOURCES: dict[str, SourceSpec] = {
    "roads": SourceSpec(
        key="roads",
        title="道路",
        profile="tile_cache_osm_else_overpass_v1",
        provider="OpenStreetMap",
        method="OSM highway ways · Overpass API",
        strategy_label="本地缓存优先，缺失时通过 Overpass API 获取 OSM highway ways",
        order=("clip_cache", "local_tile", "overpass_api"),
    ),
    "buildings": SourceSpec(
        key="buildings",
        title="建筑",
        profile="tile_cache_overture_else_overture_api_v1",
        provider="Overture Maps + Google Open Buildings",
        method="Overture 轮廓 · Google 高度补全",
        strategy_label="本地缓存优先，缺失时用 Overture 轮廓并用 Google 高度补全",
        order=("clip_cache", "local_tile", "overture_api"),
    ),
    "dem": SourceSpec(
        key="dem",
        title="地形",
        profile="fabdem_else_tile_cache_else_nasadem_v1",
        provider="FABDEM / NASADEM",
        method="FABDEM DTM 优先 · NASADEM 兜底",
        strategy_label="FABDEM DTM 优先，本地缓存命中直接恢复，失败时 NASADEM 兜底",
        order=("fabdem", "clip_cache", "local_tile", "nasadem"),
    ),
}


def acquisition_profile() -> dict:
    """Derive the cache-fingerprint profile from the registry.

    Returns the historical ``CURRENT_ACQUISITION_PROFILE`` shape exactly:
    ``{"schema": 1, "roads": <profile>, "buildings": <profile>, "dem": <profile>}``.
    Key insertion order is preserved for readability; the cache digest sorts
    keys anyway, so equality of contents is what guarantees stability.
    """
    profile: dict = {"schema": PROFILE_SCHEMA}
    for key, spec in SOURCES.items():
        profile[key] = spec.profile
    return profile


def display_items() -> list[dict]:
    """UI-facing source descriptors, in canonical group order.

    ``strategy`` mirrors the profile label so the operator sees the same token
    that lands in ``active_area.json``.
    """
    return [
        {
            "key": spec.key,
            "title": spec.title,
            "provider": spec.provider,
            "method": spec.method,
            "strategy": spec.profile,
            "strategy_label": spec.strategy_label,
        }
        for spec in SOURCES.values()
    ]