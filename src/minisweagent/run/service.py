"""Start the persistent coding-agent HTTP service."""

from pathlib import Path

import typer

app = typer.Typer()


@app.command()
def main(
    host: str = "127.0.0.1", port: int = 8000,
    data_dir: Path | None = None, repo_root: Path | None = None,
    config: Path | None = None, workers: int = typer.Option(1, min=1, max=8),
):
    import uvicorn

    from minisweagent.service.api import ServiceSettings, create_app

    settings = ServiceSettings(workers=workers)
    if data_dir is not None:
        settings.data_dir = data_dir
    if repo_root is not None:
        settings.repo_root = repo_root
    if config is not None:
        settings.config_path = config
    uvicorn.run(create_app(settings), host=host, port=port, workers=1)


if __name__ == "__main__":
    app()
