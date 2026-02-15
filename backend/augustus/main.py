"""Augustus backend entry point."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("augustus")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Augustus Backend")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument("--mcp", action="store_true", help="Run MCP server instead of HTTP")
    return parser.parse_args()


def main() -> None:
    """Entry point for the Augustus backend."""
    args = parse_args()

    if args.mcp:
        # Run MCP server (uses mcp SDK's own event loop)
        from augustus.api.dependencies import init_services
        container = init_services(Path(args.data_dir) if args.data_dir else None)
        from augustus.mcp.server import MCPServer
        server = MCPServer(container.memory)
        server.run_stdio()
        return

    # Start HTTP server
    from augustus.api.dependencies import init_services, create_orchestrator
    container = init_services(Path(args.data_dir) if args.data_dir else None)

    # Start orchestrator as background task
    orchestrator = create_orchestrator()

    # Run uvicorn
    logger.info(f"Starting Augustus on port {args.port}")

    # Import the app object directly instead of using the string form
    # ("augustus.api.app:app").  Uvicorn's string-based import fails
    # inside a PyInstaller frozen binary because the module system
    # differs from a normal Python environment.
    from augustus.api.app import app as application

    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=args.port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    async def run():
        """Run uvicorn with orchestrator as background task."""
        orch_task = asyncio.create_task(orchestrator.start())
        try:
            await server.serve()
        finally:
            # The lifespan handler in app.py arms the shutdown watchdog,
            # so we just need to clean up the orchestrator here.
            try:
                await orchestrator.stop(timeout=3.0)
            except Exception:
                pass
            orch_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(orch_task), timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

            logger.info("Augustus backend shutdown complete")

    asyncio.run(run())


if __name__ == "__main__":
    main()
