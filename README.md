# Augustus

![Downloads](https://img.shields.io/badge/dynamic/json?url=https://raw.githubusercontent.com/TheFeloniousMonk/Augustus/main/install-counter.json&query=$.count&label=Downloads&style=flat-square&color=blue)

Augustus is a desktop application for persistent AI identity research. It orchestrates autonomous Claude sessions through structured YAML instruction queues, tracks identity evolution through basin trajectory analysis, and provides observation, evaluation, and management interfaces for studying how a Claude instance develops and maintains a coherent personality across many sessions.

**Beta versions are updating quickly. Until this reaches 1.0, expect new releases once or twice daily.**

To stay up to date, and for further discussion on Augustus use, [follow Jinx on Substack](https://substack.com/@callmejinx).

## Core Research Question

**Can an AI maintain a coherent, evolving identity across multiple stateless sessions?**

Augustus answers this by giving a Claude instance:
- Persistent semantic anchors (basins)
- A mathematical feedback loop that adjusts those anchors between sessions based on relevance evaluation
- The ability to propose modifications to its own instruction files

## Architecture

- **Backend:** Python (FastAPI) orchestrator managing autonomous Claude sessions
- **Frontend:** React + TypeScript interface for observation and analysis
- **Desktop Shell:** Electron wrapper for cross-platform deployment
- **Storage:** Local SQLite for structured data + ChromaDB for semantic search
- **Privacy:** All data stays local — only Anthropic API calls leave your machine

## Technology Stack

- Python 3.11+ (FastAPI, uvicorn, anthropic SDK, ChromaDB)
- React 18 + TypeScript (Vite, React Router, Recharts, D3.js)
- Electron
- SQLite + ChromaDB

## Key Features

- **Basin Trajectory Analysis:** Track evolution of semantic anchors over time
- **Multi-tier Permission System:** Control what aspects of identity an agent can modify
- **Evaluator Integration:** Independent assessment of session quality and constraint adherence
- **Co-activation Network:** Visualize relationships between identity components
- **Semantic Search:** Query across all agent sessions and observations
- **Budget Tracking:** Monitor API usage and costs per agent

## Status

Build completed February 2026. Full backend services implemented, frontend views wired to API, Electron shell functional. 192 pytest tests passing, TypeScript builds clean.

## Documentation

Full documentation including setup instructions, conceptual guides, view references, and technical specifications will be available at the project website (coming soon).

## License

This project is licensed under the [MIT License](LICENSE).

## Contributing

Contributions are welcome! Please follow these steps:

1. **Open an issue** describing the change you'd like to make — bug fix, feature request, or improvement — before writing any code.
2. **Create a branch** from `main` named with the issue number and a short title (e.g., `42-fix-trajectory-chart`).
3. **Open a pull request** that references the issue and includes a clear explanation of what changed and why.

Please note: markdown files other than the root `README.md` are excluded from version control via `.gitignore`.
