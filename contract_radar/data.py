from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from contract_radar import config
from contract_radar.models import AwardRecord, Solicitation
from contract_radar.sample_data import sample_awards, sample_solicitations


@dataclass
class ProcurementDataBundle:
    solicitations: list[Solicitation]
    awards: list[AwardRecord]
    source_status: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    fetched_at: str = ""
    engine: str = "python_stdlib"


class ProcurementDataUnavailable(RuntimeError):
    pass


def load_procurement_data(refresh: bool = False) -> ProcurementDataBundle:
    fetched_at = _utc_now()
    warnings: list[str] = []
    source_status: dict[str, str] = {}
    engine = "python_stdlib"

    if config.env_flag(config.OFFLINE_ENV):
        solicitation_records = _load_cached_records(
            dataset_key="solicitations",
            limit=config.row_limit(),
            source_status=source_status,
            warnings=warnings,
        )
        award_records = _load_cached_records(
            dataset_key="awards",
            limit=config.row_limit(),
            source_status=source_status,
            warnings=warnings,
        )
        if solicitation_records is None or award_records is None:
            return _sample_bundle_or_raise(
                fetched_at=fetched_at,
                source_status=source_status,
                warnings=warnings,
                reason=f"{config.OFFLINE_ENV}=true but complete cached Toronto Open Data is unavailable",
            )
        solicitations = [Solicitation.from_record(record) for record in solicitation_records]
        awards = [AwardRecord.from_record(record) for record in award_records]
        warnings.append(f"{config.OFFLINE_ENV}=true; using cached Toronto Open Data only")
        return ProcurementDataBundle(
            solicitations=solicitations,
            awards=awards,
            source_status=source_status,
            warnings=warnings,
            fetched_at=fetched_at,
            engine=engine,
        )

    effective_refresh = refresh or config.env_flag(config.REFRESH_ENV)
    limit = config.row_limit()

    solicitation_records = _load_records(
        dataset_key="solicitations",
        refresh=effective_refresh,
        limit=limit,
        source_status=source_status,
        warnings=warnings,
    )
    award_records = _load_records(
        dataset_key="awards",
        refresh=effective_refresh,
        limit=limit,
        source_status=source_status,
        warnings=warnings,
    )

    if solicitation_records is None or award_records is None:
        return _sample_bundle_or_raise(
            fetched_at=fetched_at,
            source_status=source_status,
            warnings=warnings,
            reason="Live/cache Toronto Open Data is incomplete",
        )
    else:
        solicitations = [Solicitation.from_record(record) for record in solicitation_records]
        awards = [AwardRecord.from_record(record) for record in award_records]

    return ProcurementDataBundle(
        solicitations=solicitations,
        awards=awards,
        source_status=source_status,
        warnings=warnings,
        fetched_at=fetched_at,
        engine=engine,
    )


def _load_cached_records(
    dataset_key: str,
    limit: int,
    source_status: dict[str, str],
    warnings: list[str],
) -> list[dict[str, Any]] | None:
    dataset = config.DATASETS[dataset_key]
    source_name = str(dataset["name"])
    cache_path = config.CACHE_DIR / str(dataset["cache_file"])
    cached = _read_cache(cache_path)
    if cached is None:
        warnings.append(f"{source_name}: cached Toronto Open Data unavailable at {cache_path}")
        return None
    source_status[source_name] = f"cache_offline ({len(cached)} records)"
    return _prepare_records(cached, limit)


def _sample_bundle_or_raise(
    fetched_at: str,
    source_status: dict[str, str],
    warnings: list[str],
    reason: str,
) -> ProcurementDataBundle:
    if not config.env_flag(config.ALLOW_SAMPLE_DATA_ENV):
        raise ProcurementDataUnavailable(
            f"{reason}. Refusing to show bundled sample solicitations; every production posting must come "
            "from Toronto Open Data. Restore data/cache, enable network refresh, or set "
            f"{config.ALLOW_SAMPLE_DATA_ENV}=1 only for local tests."
        )

    solicitations = sample_solicitations()
    awards = sample_awards()
    source_status[config.SOLICITATIONS_SOURCE] = f"dev_sample_only ({len(solicitations)} records)"
    source_status[config.AWARDED_CONTRACTS_SOURCE] = f"dev_sample_only ({len(awards)} records)"
    warnings.append(f"{reason}; {config.ALLOW_SAMPLE_DATA_ENV}=true so bundled dev samples were used")
    return ProcurementDataBundle(
        solicitations=solicitations,
        awards=awards,
        source_status=source_status,
        warnings=warnings,
        fetched_at=fetched_at,
        engine="python_stdlib",
    )


def _load_records(
    dataset_key: str,
    refresh: bool,
    limit: int,
    source_status: dict[str, str],
    warnings: list[str],
) -> list[dict[str, Any]] | None:
    dataset = config.DATASETS[dataset_key]
    source_name = str(dataset["name"])
    cache_path = config.CACHE_DIR / str(dataset["cache_file"])

    if not refresh:
        cached = _read_cache(cache_path)
        if cached is not None:
            source_status[source_name] = f"cache ({len(cached)} records)"
            return _prepare_records(cached, limit)

    try:
        records = _fetch_datastore_search(str(dataset["resource_id"]), limit)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        warnings.append(f"{source_name}: live fetch failed ({exc})")
        cached = _read_cache(cache_path)
        if cached is not None:
            source_status[source_name] = f"cache_after_live_failure ({len(cached)} records)"
            return _prepare_records(cached, limit)
        return None

    _write_cache(cache_path, records)
    source_status[source_name] = f"live ({len(records)} records)"
    return _prepare_records(records, limit)


def _fetch_datastore_search(resource_id: str, limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    offset = 0
    page_size = min(1000, limit)

    while len(records) < limit:
        params = urlencode({"resource_id": resource_id, "limit": page_size, "offset": offset})
        with urlopen(f"{config.CKAN_DATASTORE_SEARCH_URL}?{params}", timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if not payload.get("success"):
            raise ValueError("CKAN datastore_search returned success=false")

        result = payload.get("result") or {}
        page = result.get("records") or []
        if not isinstance(page, list):
            raise ValueError("CKAN datastore_search records payload was not a list")

        records.extend([record for record in page if isinstance(record, dict)])
        total = int(result.get("total") or 0)
        if not page or len(records) >= total:
            break
        offset += len(page)

    return records[:limit]


def _read_cache(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return None
    return [record for record in records if isinstance(record, dict)]


def _write_cache(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": _utc_now(),
        "records": records,
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _prepare_records(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return records[:limit]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
