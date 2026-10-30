cat << 'EOF' > src/engine.py
from __future__ import annotations
import math
import time
from typing import Dict, List
from src.models import Hub, Trip, Vehicle, Activity, ActivityType, ChargingCurveModel
from src.planner import FleetPlanner

class PlanValidator:
    def __init__(self, cabs: List[Vehicle], hubs: List[Hub], trips: List[Trip]):
        self.cabs = cabs
        self.hubs = hubs
        self.trips = trips

    def validate(self) -> Dict:
        start_v = time.time()
        cab_violations = []
        hub_violations = []

        for cab in self.cabs:
            prev_end_t = 0
            prev_end_loc = cab.current_location

            for act in cab.schedule:
                if act.start_time < prev_end_t:
                    cab_violations.append(f"Cab {cab.id}: Overlap at min {act.start_time} (prev ended {prev_end_t})")
                if act.start_loc.distance_to(prev_end_loc) > 0.05:
                    cab_violations.append(f"Cab {cab.id}: Teleportation detected from {prev_end_loc.id} to {act.start_loc.id}")

                floor_kwh = cab.min_floor_kwh
                if act.start_soc_kwh < floor_kwh - 1e-4:
                    cab_violations.append(f"Cab {cab.id}: Start SoC {act.start_soc_kwh:.2f} kWh below 15% floor")
                if act.end_soc_kwh < floor_kwh - 1e-4:
                    cab_violations.append(f"Cab {cab.id}: End SoC {act.end_soc_kwh:.2f} kWh below 15% floor")
                if act.end_soc_kwh > cab.battery_capacity_kwh + 1e-4:
                    cab_violations.append(f"Cab {cab.id}: SoC {act.end_soc_kwh:.2f} kWh exceeded capacity ceiling")

                prev_end_t = act.end_time
                prev_end_loc = act.end_loc

        for hub in self.hubs:
            minute_usage: Dict[int, int] = {}
            for cab in self.cabs:
                for act in cab.schedule:
                    if act.act_type == ActivityType.CHARGING and act.ref_id == hub.id:
                        for m in range(act.start_time, act.end_time):
                            minute_usage[m] = minute_usage.get(m, 0) + 1

            for m, count in minute_usage.items():
                if count > hub.charger_count:
                    hub_violations.append(f"Hub {hub.id} overbooked at min {m}: {count} cabs vs {hub.charger_count} chargers")

        passed = len(cab_violations) == 0 and len(hub_violations) == 0
        return {
            "passed": passed,
            "elapsed_seconds": time.time() - start_v,
            "cab_violations": len(cab_violations),
            "hub_violations": len(hub_violations),
            "details": cab_violations[:3] + hub_violations[:3],
        }

class LiveRePlanner:
    def __init__(self, cabs: List[Vehicle], hubs: List[Hub], planner: FleetPlanner):
        self.cabs = {c.id: c for c in cabs}
        self.hubs = {h.id: h for h in hubs}
        self.planner = planner
        self.curve = ChargingCurveModel()

    def handle_battery_drift(self, cab_id: str, current_time: int, real_soc_pct: float) -> Dict:
        t0 = time.time()
        cab = self.cabs[cab_id]
        real_soc_kwh = (real_soc_pct / 100.0) * cab.battery_capacity_kwh
        hub = list(self.hubs.values())[0]

        future_acts = [a for a in cab.schedule if a.start_time >= current_time]
        next_trip_act = next((a for a in future_acts if a.act_type == ActivityType.TRIP), None)
        if not next_trip_act:
            return {"status": "NO_UPCOMING_TRIPS", "elapsed_seconds": time.time() - t0}

        trip_id = next_trip_act.ref_id
        current_loc = next_trip_act.start_loc
        cab.schedule = [a for a in cab.schedule if a.end_time <= current_time]

        best_peer = None
        min_dh = float("inf")
        peer_dh_t = 0
        peer_soc_arr = 0.0
        peer_soc_end = 0.0
        trip_energy = next_trip_act.start_soc_kwh - next_trip_act.end_soc_kwh

        for peer_id, peer in self.cabs.items():
            if peer_id == cab_id:
                continue
            last_t = peer.schedule[-1].end_time if peer.schedule else 960
            last_loc = peer.schedule[-1].end_loc if peer.schedule else peer.current_location
            last_soc = peer.schedule[-1].end_soc_kwh if peer.schedule else peer.initial_soc_kwh

            if last_t <= next_trip_act.start_time:
                d = last_loc.distance_to(next_trip_act.start_loc)
                tt = int(math.ceil((d / peer.speed_kmh) * 60))
                if last_t + tt <= next_trip_act.start_time:
                    soc_arr = last_soc - (d * peer.consumption_per_km)
                    soc_end = soc_arr - trip_energy
                    ret_h = next_trip_act.end_loc.distance_to(hub.location) * peer.consumption_per_km
                    if soc_arr >= peer.min_floor_kwh and (soc_end - ret_h) >= peer.min_floor_kwh:
                        if d < min_dh:
                            min_dh = d
                            best_peer = peer
                            peer_dh_t = tt
                            peer_soc_arr = soc_arr
                            peer_soc_end = soc_end

        reassigned_to = None
        assignments_changed = 0

        if best_peer:
            p_last_loc = best_peer.schedule[-1].end_loc if best_peer.schedule else best_peer.current_location
            p_last_soc = best_peer.schedule[-1].end_soc_kwh if best_peer.schedule else best_peer.initial_soc_kwh

            best_peer.schedule.append(Activity(
                act_type=ActivityType.EMPTY_DRIVE,
                start_time=next_trip_act.start_time - peer_dh_t,
                end_time=next_trip_act.start_time,
                start_loc=p_last_loc,
                end_loc=next_trip_act.start_loc,
                start_soc_kwh=p_last_soc,
                end_soc_kwh=peer_soc_arr,
                ref_id=f"REASSIGN_TO_{trip_id}"
            ))
            best_peer.schedule.append(Activity(
                act_type=ActivityType.TRIP,
                start_time=next_trip_act.start_time,
                end_time=next_trip_act.end_time,
                start_loc=next_trip_act.start_loc,
                end_loc=next_trip_act.end_loc,
                start_soc_kwh=peer_soc_arr,
                end_soc_kwh=peer_soc_end,
                ref_id=trip_id
            ))
            reassigned_to = best_peer.id
            assignments_changed += 1

        dh_hub = current_loc.distance_to(hub.location)
        t_hub = int(math.ceil((dh_hub / cab.speed_kmh) * 60))
        arr_hub = current_time + t_hub
        soc_hub = real_soc_kwh - (dh_hub * cab.consumption_per_km)

        cab.schedule.append(Activity(
            act_type=ActivityType.EMPTY_DRIVE,
            start_time=current_time,
            end_time=arr_hub,
            start_loc=current_loc,
            end_loc=hub.location,
            start_soc_kwh=real_soc_kwh,
            end_soc_kwh=soc_hub,
            ref_id="DIVERSION_TO_HUB"
        ))

        dep_hub = arr_hub + 45
        self.planner.book_charger(hub, arr_hub, dep_hub)
        e_added = self.curve.energy_added_in_minutes(soc_hub, 45, cab.battery_capacity_kwh, hub.charger_power_kw)
        cab.schedule.append(Activity(
            act_type=ActivityType.CHARGING,
            start_time=arr_hub,
            end_time=dep_hub,
            start_loc=hub.location,
            end_loc=hub.location,
            start_soc_kwh=soc_hub,
            end_soc_kwh=soc_hub + e_added,
            ref_id=hub.id,
            cost=e_added * hub.get_tariff(arr_hub)
        ))
        assignments_changed += 1

        return {
            "status": "SUCCESS",
            "elapsed_seconds": time.time() - t0,
            "drifted_cab": cab_id,
            "offloaded_trip": trip_id,
            "reassigned_peer": reassigned_to,
            "drifted_cab_rerouted_hub": hub.id,
            "assignments_changed": assignments_changed,
        }

    def handle_charger_failure(self, hub_id: str, break_time: int) -> Dict:
        t0 = time.time()
        hub = self.hubs[hub_id]
        hub.charger_count -= 1
        rescheduled_sessions = 0

        sessions = []
        for cab in self.cabs.values():
            for act in cab.schedule:
                if act.act_type == ActivityType.CHARGING and act.ref_id == hub_id and act.end_time > break_time:
                    sessions.append(act)

        sessions.sort(key=lambda a: a.start_time)
        for act in sessions:
            overlap = sum(
                1 for o in sessions if max(act.start_time, o.start_time) < min(act.end_time, o.end_time)
            )
            if overlap > hub.charger_count:
                self.planner.release_charger(hub, act.start_time, act.end_time)
                act.start_time += 15
                act.end_time += 15
                self.planner.book_charger(hub, act.start_time, act.end_time)
                rescheduled_sessions += 1
                break

        return {
            "status": "SUCCESS",
            "hub": hub_id,
            "new_charger_capacity": hub.charger_count,
            "rescheduled_sessions": rescheduled_sessions,
            "elapsed_seconds": time.time() - t0,
        }
EOF
