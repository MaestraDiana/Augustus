# Augustus

Augustus is a desktop application for persistent AI identity research. It orchestrates autonomous Claude sessions through structured YAML instruction queues, tracks identity evolution through basin trajectory analysis, and provides observation, evaluation, and management interfaces for studying how a Claude instance develops and maintains a coherent personality across many sessions.

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

[License TBD]

## Contributing

[Contribution guidelines TBD]
