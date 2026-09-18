from fastapi import FastAPI, HTTPException, status

from schemas import OptimizeRequest, OptimizeResponse
from interpreter import interpret_and_guardrail
from optimizer import solve_energy_optimization

app = FastAPI(title="GridWise LLM Energy Service")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeResponse)
def optimize_energy(request: OptimizeRequest):
    try:
        directive_entries, applied_directives = interpret_and_guardrail(request)
        response = solve_energy_optimization(
            request,
            applied_directives,
            directive_entries
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal Server Error: {str(e)}"
        )


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "GridWise Backend",
        "docs": "/docs",
        "health": "/health"
    }