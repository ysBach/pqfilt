"""Click CLI for pqfilt."""

from __future__ import annotations

import sys

import click

from .core import write_filtered


@click.command()
@click.argument("files", nargs=-1, required=True, type=click.Path())
@click.option(
    "-f",
    "--filter",
    "filter_exprs",
    multiple=True,
    help=(
        'Filter expression, e.g. "vmag < 20", "(a < 30 & b > 50) | c == 1". '
        "Multiple -f flags are AND-ed together."
    ),
)
@click.option(
    "-o",
    "--output",
    required=True,
    type=click.Path(),
    help="Output file path (.parquet or .csv).",
)
@click.option("--overwrite", is_flag=True, help="Overwrite output if it exists.")
@click.option("--columns", default=None, help="Comma-separated list of columns to include.")
@click.option(
    "--per-file/--no-per-file",
    expose_value=False,
    help="Deprecated no-op; PyArrow dataset scanning is always used.",
)
def main(
    files: tuple[str, ...],
    filter_exprs: tuple[str, ...],
    output: str,
    overwrite: bool,
    columns: str | None,
) -> None:
    """Filter Parquet files with predicate pushdown.

    FILES are one or more Parquet file paths or glob patterns.

    Examples
    --------
    Filter by magnitude::

        pqfilt data/*.parquet -f "vmag < 20" -o filtered.parquet

    Boolean expression (AND / OR)::

        pqfilt data/*.parquet -f "(a < 30 & b > 50) | c == 1" -o out.parquet

    Membership filter::

        pqfilt data/*.parquet -f "desig in 1,2,3" --columns desig,ra,dec -o out.parquet
    """
    # Parse columns
    columns_list = [c.strip() for c in columns.split(",")] if columns else None

    # Combine multiple -f expressions with AND
    combined_filter: str | None = None
    if filter_exprs:
        if len(filter_exprs) == 1:
            combined_filter = filter_exprs[0]
        else:
            # Wrap each expression in parens and AND them
            combined_filter = " & ".join(f"({expr})" for expr in filter_exprs)

    # Resolve file list
    filelist: str | list[str]
    if len(files) == 1:
        filelist = files[0]
    else:
        filelist = list(files)

    try:
        rows_written = write_filtered(
            source=filelist,
            output=output,
            filters=combined_filter,
            columns=columns_list,
            overwrite=overwrite,
        )
        click.echo(f"Filtered {rows_written} rows -> {output}", err=True)

    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except FileExistsError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except ValueError as e:
        click.echo(f"Filter error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
