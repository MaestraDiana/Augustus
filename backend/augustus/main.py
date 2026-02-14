"""Augustus backend entry point."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
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

    config = uvicorn.Config(
        "augustus.api.app:app",
        host="127.0.0.1",
        port=args.port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    async def run():
        """Run uvicorn with orchestrator as background task."""
        # Start orchestrator in background
        orch_task = asyncio.create_task(orchestrator.start())
        try:
            await server.serve()
        finally:
            await orchestrator.stop()
            orch_task.cancel()

    asyncio.run(run())


if __name__ == "__main__":
    main()
