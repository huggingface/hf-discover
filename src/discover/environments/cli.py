from pathlib import Path
from typing import Annotated

import typer

from discover.models import SearchQuery, SearchRequest

from .catalog import CatalogQueryError, CatalogReadError, search_catalog
from .models import ENVIRONMENT_MEDIA_TYPE


def environments(
    query: Annotated[str, typer.Argument(help="Task to find an environment for.")],
    catalog: Annotated[Path, typer.Option(help="Explicit local versioned metadata snapshot.")],
    json_output: Annotated[bool, typer.Option("--json", help="Emit complete ARD results.")] = False,
    limit: Annotated[int, typer.Option(min=1, max=100)] = 10,
) -> None:
    """Search a declared OpenEnv snapshot before installation or execution."""
    request = SearchRequest(
        query=SearchQuery(text=query, filter={"type": [ENVIRONMENT_MEDIA_TYPE]}),
        pageSize=limit,
    )
    try:
        response = search_catalog(catalog, request)
    except (CatalogReadError, CatalogQueryError) as error:
        raise typer.BadParameter(str(error), param_hint="--catalog") from error
    if json_output:
        typer.echo(response.model_dump_json(exclude_none=True, indent=2))
        return
    for result in response.results:
        typer.echo(f"{result.displayName}: {result.description}")
        typer.echo(result.model_dump_json(exclude_none=True, indent=2))
    typer.echo("Metadata only. No candidate code or endpoint was invoked.")
