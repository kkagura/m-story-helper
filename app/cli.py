import argparse
import logging
from pathlib import Path

import uvicorn

from app import __version__
from app.api.server import create_app
from app.config import DEFAULT_CONFIG, Settings, load_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="maple-vision", description="Maple Vision Lab")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the local HTTP service")
    serve.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    serve.add_argument("--host", choices=["127.0.0.1", "localhost"])
    serve.add_argument("--port", type=int)
    args = parser.parse_args()

    try:
        configured = load_settings(args.config).model_dump()
        if args.host is not None:
            configured["host"] = args.host
        if args.port is not None:
            configured["port"] = args.port
        settings = Settings.model_validate(configured)
    except (OSError, ValueError) as exc:
        parser.error(f"Unable to load configuration: {exc}")

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger(__name__).info("Local address: http://%s:%s", settings.host, settings.port)
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
