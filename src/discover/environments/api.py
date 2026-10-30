from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from .catalog import CatalogQueryError, CatalogReadError, search_catalog
from .models import ENVIRONMENT_MEDIA_TYPE

if TYPE_CHECKING:
    from pathlib import Path

    from discover.models import SearchRequest, SearchResponse


def environment_search(request: SearchRequest, catalog: Path | None) -> SearchResponse | None:
    values = request.query.filter.get("type", [])
    kinds = values if isinstance(values, list) else [values]
    if ENVIRONMENT_MEDIA_TYPE not in kinds:
        return None
    if set(kinds) != {ENVIRONMENT_MEDIA_TYPE}:
        raise HTTPException(
            400, "Search the environment profile separately from live resource types"
        )
    try:
        return search_catalog(catalog, request)
    except CatalogReadError as error:
        raise HTTPException(503, str(error)) from error
    except CatalogQueryError as error:
        raise HTTPException(400, str(error)) from error
