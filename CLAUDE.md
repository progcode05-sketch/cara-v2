# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**CARA** is the backend for Noxlin — a LinkedIn growth system that turns ideas into professional LinkedIn carousels. It handles AI-driven content planning, HTML-template rendering, and LinkedIn publishing via a FastAPI server.

## Development Commands

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the dev server (with auto-reload)
python run_local_dashboard.py --port 3002 --reload
# Or directly:
uvicorn app.main:app --reload --port 3002

# Run tests
pytest tests/ -v

# Run a single test file
pytest tests/test_foo.py -v

# Build/import templates
python build_templates.py
```

## Required Environment Variables

Set in `.env` or environment before running:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API (content generation) |
| `GEMINI_API_KEY` | Gemini image generation |
| `LINKEDIN_CLIENT_ID` | LinkedIn OAuth |
| `LINKEDIN_CLIENT_SECRET` | LinkedIn OAuth |
| `NOXLIN_PORT` | Server port (default: 3002) |

## Architecture

### Request Flow: Carousel Generation

```
POST /carousels/generate
  → CarouselService.generate()
      → InputAuthenticatorAgent     (validates topic/brief)
      → CaptainWritingAgent         (produces CarouselPlan with slide content)
      → image_generation            (Gemini API, with placeholder fallback)
      → renderer                    (HTML template → SVG previews → PDF)
  → persisted in data/carousels/{id}.json
```

### Key Layers

- **`app/domain.py`** — Core dataclasses (`CarouselPlan`, `TemplatePackage`, `SlideContent`). These are the internal model; everything else depends on them.
- **`app/schemas.py`** — Pydantic request/response schemas (API boundary types, separate from domain).
- **`app/services/orchestrator.py`** — Claude-powered AI planning. Two-agent pipeline: `InputAuthenticatorAgent` then `CaptainWritingAgent`. Uses `claude-sonnet-4-20250514`.
- **`app/services/renderer.py`** — HTML template → SVG → PDF pipeline. Templates are slot-filled HTML; renderer produces static artifacts.
- **`app/services/carousel_service.py`** — Orchestrates the full pipeline; the main business logic entry point.
- **`app/repositories.py`** — File-based persistence. Carousels, templates, profiles, and OAuth state are stored as JSON under `data/`.
- **`app/bootstrap.py`** — Service container / DI wiring. All services are instantiated here and injected via `app/dependencies.py`.
- **`app/api/routes/agent_stream.py`** — SSE endpoint for live agent event streaming during generation.

### Template System

Templates live in `data/templates/` as `TemplatePackage` objects (HTML + CSS + manifest). They define named slots that `CaptainWritingAgent` fills with generated content. Import new templates via `POST /templates/import` or `build_templates.py`.

### Data Storage (`data/`)

All persistence is file-based (no database):
- `data/carousels/` — Generated `CarouselPlan` JSON files, keyed by ID
- `data/templates/` — Imported template packages
- `data/artifacts/` — Rendered HTML, SVG, PDF outputs served at `/artifacts/*`
- `data/profiles/` — User profile JSON
- `data/oauth/` — LinkedIn OAuth state

## API Surface

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/carousels/generate` | Create a carousel |
| `GET` | `/carousels/{id}` | Retrieve carousel |
| `POST` | `/carousels/{id}/regenerate-slide` | Regenerate one slide |
| `GET/POST` | `/templates/*` | Template catalog and import |
| `GET/POST` | `/auth/linkedin/*` | LinkedIn OAuth flow |
| `GET` | `/artifacts/*` | Serve rendered files |
| `GET` | `/dashboard` | Web UI |
| `GET` | `/health` | Health check |

## AI Client Notes

- **Anthropic** (`app/services/ai_clients.py`): Used for all text content — planning, writing, validation. Model: `claude-sonnet-4-20250514`.
- **Gemini** (`app/services/image_generation.py`): Used for slide images (`gemini-2.5-flash-image`). Falls back to placeholders on failure.
- Agent events are streamed via SSE (`app/services/agent_events.py`) so the frontend can show live progress.
