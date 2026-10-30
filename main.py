cat << 'EOF' > main.py
import math
import random
from src.models import Hub, Location, Trip, Vehicle
from src.planner import FleetPlanner
from src.engine import PlanValidator, LiveRePlanner

if __name__ == "__main__":
    print("=" * 70)
    print("MoveInSync Case Study 6: EV Fleet Charging & Trip Assignment")
    print("=" * 70)

    random.seed(42)
    hub = Hub(
        id="HUB_CENTRAL",
        location=Location("LOC_HUB", 20.0, 20.0),
        charger_count=40,
        charger_power_kw=60.0
    )

    cabs = [
        Vehicle(
            id=f"CAB_{i:03d}",
            battery_capacity_kwh=50.0,
            initial_soc_kwh=random.uniform(0.60, 0.90) * 50.0,
            consumption_per_km=round(random.uniform(0.18, 0.22), 3),
            current_location=Location(f"LOC_CAB_{i}", random.uniform(5.0, 35.0), random.uniform(5.0, 35.0))
        )
        for i in range(300)
    ]

    trips = []
    for i in range(1500):
        st = random.randint(960, 1380)
        sx, sy = random.uniform(2.0, 38.0), random.uniform(2.0, 38.0)
        ex, ey = random.uniform(2.0, 38.0), random.uniform(2.0, 38.0)
        dist = max(5.0, math.hypot(ex - sx, ey - sy))
        dur = int(math.ceil((dist / 35.0) * 60))
        trips.append(
            Trip(
                id=f"TRIP_{i:04d}",
                start_loc=Location(f"S_{i}", sx, sy),
                end_loc=Location(f"E_{i}", ex, ey),
                start_time=st,
                end_time=st + dur,
                distance_km=dist,
                latest_finish=st + dur + 20,
                energy_kwh=dist * 0.20
            )
        )

    print("\n[1] Starting 300-cab, 1500-trip day planning...")
    planner = FleetPlanner(cabs, [hub], trips)
    res = planner.plan()
    print(f"    - Execution Time: {res['elapsed_seconds']:.4f}s (Target < 30s)")
    print(f"    - Electric Trips Assigned: {res['assigned_count']} / 1500 ({res['assigned_count']/15:.2f}%)")
    print(f"    - Trips Sent to Backup:    {res['backup_count']}")

    print("\n[2] Running Independent Invariant Validator...")
    validator = PlanValidator(cabs, [hub], trips)
    v_res = validator.validate()
    print(f"    - Invariants Passed:        {v_res['passed']}")
    print(f"    - Battery Floor Violations: {v_res['cab_violations']}")
    print(f"    - Charger Overbookings:     {v_res['hub_violations']}")

    print("\n[3] Triggering Live Battery Drift Event...")
    replanner = LiveRePlanner(cabs, [hub], planner)
    d_res = replanner.handle_battery_drift("CAB_005", current_time=1050, real_soc_pct=22.0)
    print(f"    - Re-planning Time:   {d_res['elapsed_seconds']*1000:.2f} ms (Target < 2000 ms)")
    print(f"    - Offloaded Trip:     {d_res['offloaded_trip']}")
    print(f"    - Reassigned to Peer: {d_res['reassigned_peer']}")
    print(f"    - Assignments Changed:{d_res['assignments_changed']}")

    print("\n[4] Triggering Live Charger Failure Event...")
    f_res = replanner.handle_charger_failure("HUB_CENTRAL", break_time=1080)
    print(f"    - Re-planning Time:   {f_res['elapsed_seconds']*1000:.2f} ms (Target < 2000 ms)")
    print(f"    - Rescheduled Queues: {f_res['rescheduled_sessions']}")
EOF
