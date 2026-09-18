import pulp
from typing import List, Dict, Any, Tuple
from schemas import OptimizeRequest, HourlyPlanEntry, OptimizeResponse

def solve_energy_optimization(
    request: OptimizeRequest,
    directives: List[Dict[str, Any]],
    directive_entries: list
) -> OptimizeResponse:
    hours = request.hours
    batt = request.battery

    # 1. Effective Solar
    effective_solar = [h.solar_kwh for h in hours]
    for d in directives:
        if d["type"] == "solar_reduction":
            factor = d["adj"]["factor"]
            for hr in d["adj"]["hours"]:
                effective_solar[hr] *= factor

    # 2. Minimum Battery Reserve per Hour
    min_reserve = [batt.minimum_energy_kwh for _ in range(24)]
    for d in directives:
        if d["type"] == "minimum_battery_reserve":
            req_res = d["adj"]["minimum_energy_kwh"]
            for hr in d["adj"]["hours"]:
                min_reserve[hr] = max(min_reserve[hr], req_res)

    # 3. Decision Windows
    no_charge_hrs = set()
    no_discharge_hrs = set()
    max_grid_caps = {}

    for d in directives:
        if d["type"] == "no_charge_window":
            no_charge_hrs.update(d["adj"]["hours"])
        elif d["type"] == "no_discharge_window":
            no_discharge_hrs.update(d["adj"]["hours"])
        elif d["type"] == "max_grid_window":
            cap = d["adj"]["max_grid_kwh"]
            for hr in d["adj"]["hours"]:
                max_grid_caps[hr] = min(max_grid_caps.get(hr, float('inf')), cap)

    # 4. PuLP Model Setup
    model = pulp.LpProblem("GridWise_Optimization", pulp.LpMinimize)

    grid = [pulp.LpVariable(f"grid_{h}", lowBound=0) for h in range(24)]
    solar_used = [pulp.LpVariable(f"solar_used_{h}", lowBound=0) for h in range(24)]
    charge = [pulp.LpVariable(f"charge_{h}", lowBound=0, upBound=batt.max_charge_kwh_per_hour) for h in range(24)]
    discharge = [pulp.LpVariable(f"discharge_{h}", lowBound=0, upBound=batt.max_discharge_kwh_per_hour) for h in range(24)]
    soc = [pulp.LpVariable(f"soc_{h}", lowBound=0, upBound=batt.capacity_kwh) for h in range(24)]

    # Objective: Minimize Electricity Cost
    model += pulp.lpSum([grid[h] * hours[h].tariff_bdt_per_kwh for h in range(24)])

    # Constraints
    for h in range(24):
        # Solar Limit
        model += solar_used[h] <= effective_solar[h]

        # Grid Window Cap
        if h in max_grid_caps:
            model += grid[h] <= max_grid_caps[h]

        # No Charge / No Discharge Windows
        if h in no_charge_hrs:
            model += charge[h] == 0
        if h in no_discharge_hrs:
            model += discharge[h] == 0

        # Energy Balance Equation
        model += grid[h] + solar_used[h] + discharge[h] == hours[h].demand_kwh + charge[h]

        # Battery State Transition
        prev_soc = batt.initial_energy_kwh if h == 0 else soc[h - 1]
        model += soc[h] == prev_soc + charge[h] - discharge[h]

        # Minimum Battery Reserve Constraint
        model += soc[h] >= min_reserve[h]

    # End-of-Day Neutrality
    model += soc[23] == batt.initial_energy_kwh

    model.solve(pulp.PULP_CBC_CMD(msg=False))

    # Construct Response Plan
    hourly_plans: List[HourlyPlanEntry] = []
    for h in range(24):
        g_val = max(0.0, float(pulp.value(grid[h])))
        s_val = max(0.0, float(pulp.value(solar_used[h])))
        c_val = max(0.0, float(pulp.value(charge[h])))
        d_val = max(0.0, float(pulp.value(discharge[h])))
        e_val = max(0.0, float(pulp.value(soc[h])))

        if c_val > 0.01:
            action = "charge"
            b_kwh = c_val
        elif d_val > 0.01:
            action = "discharge"
            b_kwh = d_val
        else:
            action = "idle"
            b_kwh = 0.0

        hourly_plans.append(HourlyPlanEntry(
            hour=h,
            grid_kwh=round(g_val, 2),
            solar_used_kwh=round(s_val, 2),
            battery_action=action,
            battery_kwh=round(b_kwh, 2),
            battery_energy_after_kwh=round(e_val, 2)
        ))

    tot_grid = round(sum(p.grid_kwh for p in hourly_plans), 2)
    tot_cost = round(sum(hourly_plans[h].grid_kwh * hours[h].tariff_bdt_per_kwh for h in range(24)), 2)
    peak_grid = round(max(p.grid_kwh for p in hourly_plans), 2)

    return OptimizeResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=directive_entries,
        hourly_plan=hourly_plans,
        total_grid_kwh=tot_grid,
        total_cost_bdt=tot_cost,
        peak_grid_kwh=peak_grid,
        plan_summary=f"Optimized 24-hour grid cost to {tot_cost} BDT using LP solver and Gemini LLM directives."
    )