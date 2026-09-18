import os
from typing import List, Tuple
from google import genai
from google.genai import types
from schemas import (
    OptimizeRequest,
    GeminiInterpretationResponse,
    DirectiveInterpretationEntry,
)

SYSTEM_PROMPT = """You are an expert energy grid operator assistant.
Analyze each natural language operator note for a 24-hour smart campus energy schedule (hours 0 to 23).
Convert relevant notes into supported directive types or mark them as no_op if irrelevant.

Supported Directives:
1. solar_reduction: PV output drops. Requires 'hours' (0-23) and 'factor' (0.0 to 1.0, e.g. 80% drop means factor = 0.2).
2. minimum_battery_reserve: Keep minimum battery reserve. Requires 'hours' and 'minimum_energy_kwh'.
3. no_charge_window: Charging disabled. Requires 'hours'.
4. no_discharge_window: Discharging disabled. Requires 'hours'.
5. max_grid_window: Max grid import limit. Requires 'hours' and 'max_grid_kwh'.
6. no_op: Irrelevant or informational note.

Time mapping: 1 PM to 3 PM means hours [13, 14].
Return exactly one interpretation for every operator note in note_index order (0 to N-1).
"""

def interpret_and_guardrail(
    request: OptimizeRequest
) -> Tuple[List[DirectiveInterpretationEntry], List[dict]]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing!")

    client = genai.Client(api_key=api_key)
    
    prompt = f"Operator Notes to interpret:\n"
    for idx, note in enumerate(request.operator_notes):
        prompt += f"Note Index {idx}: '{note}'\n"

    validated_entries: List[DirectiveInterpretationEntry] = []
    applied_directives: List[dict] = []

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=GeminiInterpretationResponse,
                temperature=0.0,
            ),
        )
        parsed: GeminiInterpretationResponse = response.parsed
        raw_dict = {d.note_index: d for d in parsed.directives}
    except Exception as e:
        raw_dict = {}

    for idx in range(len(request.operator_notes)):
        raw = raw_dict.get(idx)
        if not raw or raw.directive_type == "no_op":
            entry = DirectiveInterpretationEntry(
                note_index=idx,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation=raw.explanation if raw else "Informational note, no schedule impact."
            )
            validated_entries.append(entry)
            continue

        # --- Deterministic Guardrails ---
        valid_hours = sorted(list(set([h for h in (raw.hours or []) if 0 <= h <= 23])))
        if not valid_hours:
            validated_entries.append(DirectiveInterpretationEntry(
                note_index=idx, applies=False, directive_type="no_op",
                structured_adjustment=None, explanation="Invalid or empty hours provided."
            ))
            continue

        d_type = raw.directive_type
        adj = {"hours": valid_hours}
        is_valid = True

        if d_type == "solar_reduction":
            factor = raw.factor if raw.factor is not None else 1.0
            factor = max(0.0, min(1.0, float(factor)))
            adj["factor"] = round(factor, 4)
        elif d_type == "minimum_battery_reserve":
            reserve = max(0.0, float(raw.minimum_energy_kwh or 0))
            reserve = min(reserve, request.battery.capacity_kwh)
            adj["minimum_energy_kwh"] = round(reserve, 2)
        elif d_type in ["no_charge_window", "no_discharge_window"]:
            pass
        elif d_type == "max_grid_window":
            grid_cap = max(0.0, float(raw.max_grid_kwh or 0))
            adj["max_grid_kwh"] = round(grid_cap, 2)
        else:
            is_valid = False

        if is_valid:
            entry = DirectiveInterpretationEntry(
                note_index=idx,
                applies=True,
                directive_type=d_type,
                structured_adjustment=adj,
                explanation=raw.explanation or f"Applied {d_type} directive."
            )
            validated_entries.append(entry)
            applied_directives.append({"type": d_type, "adj": adj})
        else:
            validated_entries.append(DirectiveInterpretationEntry(
                note_index=idx, applies=False, directive_type="no_op",
                structured_adjustment=None, explanation="Failed guardrail validation."
            ))

    return validated_entries, applied_directives