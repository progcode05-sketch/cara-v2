# Carousel Backend

FastAPI backend scaffold for a template-grounded carousel generation system.

## What is included

- Template ingestion for `html` and `pdf`-style references
- Built-in template library with JSON + HTML template packages
- Carousel orchestration that constrains slides to template slot schemas
- Two generation modes:
  - `slot_fill`
  - `full_slide`
- Evaluation harness that can compare multiple generation modes on the same brief
- Deterministic preview + PDF export with filesystem-backed artifacts
- Single-slide regeneration without rebuilding the whole deck

## Structure

- `app/main.py`: FastAPI app entrypoint
- `app/services/`: orchestration, ingestion, image generation, rendering
- `app/builtin_templates/`: starter template packages
- `data/`: runtime storage for imported templates, carousels, and artifacts
- `tests/`: service-level regression tests

## Run locally

```bash
uvicorn app.main:app --reload
```

Then open:

```text
/dashboard
```

The Noxlin-style carousel dashboard lets you:

- type only a topic to generate a test carousel
- choose from the imported LN templates
- preview the rendered deck
- connect a LinkedIn account through backend OAuth routes

LinkedIn auth routes:

```text
GET  /auth/linkedin/status
GET  /auth/linkedin/url
GET  /auth/linkedin/start
GET  /auth/linkedin/callback
POST /auth/linkedin/disconnect
```

## Notes

- Image generation is implemented as a pluggable backend stub. It writes prompt-packed placeholder assets so you can swap in Nano Banana or another model later without changing the surrounding pipeline.
- PDF export is deterministic and dependency-free. It is intentionally simple, but it produces stable multi-page PDFs suitable for backend testing and workflow integration.
