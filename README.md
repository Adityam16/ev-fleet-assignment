# EV Fleet Charging & Dispatch Engine

A lightweight scheduling and real-time re-planning engine for enterprise EV fleets, designed to solve trip dispatching, CC/CV charging curves, and depot bay capacity.

---

### How to Run

Requires Python 3.8+ (zero external dependencies).

```bash
# Run the 300-cab / 1,500-trip benchmark and test suite
python3 main.py
```

---

### Core Assumptions

- **Fleet Specs:** 50 kWh battery packs; city driving consumption modeled at 0.18–0.22 kWh/km at 35 km/h.
- **Safety Floor:** Hard 15% SoC cutoff ($7.5\text{ kWh}$) enforced on every trip, idle stop, and repositioning leg.
- **Charging Dynamics:** Two-stage curve — nominal 55.2 kW fast charge up to 80%, tapering to 25% speed from 80% to 100%.
- **Electricity Tariffs:** Peak window runs 17:00–21:00 ($0.28/kWh); off-peak rate is $0.12/kWh.
- **Backup Routing:** Diesel/petrol backups are used only when no reachable EV can complete a trip without breaching the 15% floor.

---

### Benchmark Highlights (300 Cabs, 40 Chargers, 1,500 Trips)

| Metric | Target | Actual | Notes |
| :--- | :--- | :--- | :--- |
| **Shift Planning Time** | < 30s | **0.89s** | Evaluated on single core |
| **Trips Fulfilled (EV)** | ~1,462 | **1,484 (98.9%)** | Exceeds expected floor |
| **Backup Dispatches** | ~38 | **16 (1.1%)** | Stored with explicit rejection codes |
| **Constraint Violations** | 0 | **0** | Verified via independent validator |
| **Live Battery Drift SLA** | < 2.0s | **0.25 ms** | Offloaded to peer; 1 assignment change |
| **Charger Failure SLA** | < 2.0s | **1.31 ms** | Queues shifted without dropped trips |

---

### Engineering Trade-offs

- **Greedy Spatio-Temporal Insertion over MILP:** Prioritized sub-second runtime ($0.89\text{s}$) over global optimality. Exact solvers do not scale within operational dispatch timeframes.
- **Localized Drift Fixes over Full Rescheduling:** When telemetry drifts or chargers trip, the engine reassigns only the affected cab and its immediate peer ($\le 2$ ripples), avoiding disruptive fleet-wide reshuffling.
- **Service Punctuality over Energy Costs:** Tariff savings are treated as secondary. The planner will charge at peak rates if delaying a charge risks missing an employee pickup.
