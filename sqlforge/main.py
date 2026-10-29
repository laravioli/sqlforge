import platform
from pathlib import Path

import click

import sqlforge

from .config import load_cfg


def print_version(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(
        "Running sqlforge {version} with {py_implementation} {py_version} on {system}".format(  # noqa: UP032
            version=sqlforge.__version__,
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
    click.echo("TODO")


@cli.command()
@click.option(
    "--file",
    "-f",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=None,
    help="Config file (sqlforge.toml / pyproject.toml)",
)
def gen(file: Path | None):
    """Generate code from the SQL files in SRCS directories."""
    cfg = load_cfg(file or Path.cwd())
    click.echo(cfg)


if __name__ == "__main__":
    cli()
