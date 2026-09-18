# GridWise Smart Campus Energy Optimizer

LLM-assisted energy scheduling API for BUP CSE Fest 2026.

## Architecture

- **LLM:** Gemini 2.5 Flash for natural language operator note interpretation.
- **Guardrails:** Deterministic validation for hour limits, factor bounds, and safety constraints.
- **Solver:** PuLP Linear Programming optimization for minimum grid cost and battery scheduling.

## Setup & Execution

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="your_api_key"
uvicorn main:app --host 0.0.0.0 --port 8001

## Endpoints

- `GET /health` - Readiness check
- `POST /optimize-energy` - Optimization endpoint