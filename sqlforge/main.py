from pathlib import Path

import click

from .errors import SqlforgeError


def print_version(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return

    import importlib.metadata
    import platform

    click.echo(
        "Running sqlforge {version} with {py_implementation} {py_version} on {system}".format(
            version=importlib.metadata.version("sqlforge"),
            py_implementation=platform.python_implementation(),
            py_version=platform.python_version(),
            system=platform.system(),
        )
    )
    ctx.exit()


@click.group()
@click.option(
    "--version",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
    help="Display sqlforge version and exit.",
)
def cli(): ...


@cli.command()
def init():
    """Create an empty sqlforge.toml config file."""
    click.echo("TODO")


@cli.command()
@click.option(
    "--file",
    "-f",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to a config file (toml format)",
)
def gen(file: Path | None):
    """Generate typed code from the sql files."""
    from .config import load_cfg
    from .loader import load_sql

    try:
        cfg = load_cfg(file or Path.cwd())
        sqls = load_sql(cfg)
    except SqlforgeError as e:
        raise click.ClickException(str(e)) from e

    if not sqls:
        click.echo(
            "Warning: no SQL queries found in sources, nothing to generate", err=True
        )
        return

    import asyncio

    from .forge import Blacksmith
    from .writer import write

    try:
        write(cfg.out, asyncio.run(Blacksmith.forge(cfg, sqls)))
    except (ConnectionError, SqlforgeError) as e:
        raise click.ClickException(str(e)) from e


if __name__ == "__main__":
    cli()
