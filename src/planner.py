cat << 'EOF' > src/planner.py
from __future__ import annotations
import math
import time
from typing import Dict, List
from src.models import Hub, Trip, Vehicle, Activity, ActivityType, ChargingCurveModel

class FleetPlanner:
    def __init__(self, cabs: List[Vehicle], hubs: List[Hub], trips: List[Trip]):
        self.cabs = cabs
        self.hubs = hubs
        self.trips = trips
        self.curve = ChargingCurveModel()
        self.sim_start = 900
        self.sim_end = 1500
        self.hub_occupancy: Dict[str, List[int]] = {
            h.id: [0] * (self.sim_end - self.sim_start + 60) for h in hubs
        }
        self.assigned_trips: List[Trip] = []
        self.backup_trips: List[Trip] = []

    def can_book_charger(self, hub: Hub, start_min: int, end_min: int) -> bool:
        idx_s = max(0, start_min - self.sim_start)
        idx_e = min(len(self.hub_occupancy[hub.id]), end_min - self.sim_start)
        return all(self.hub_occupancy[hub.id][t] < hub.charger_count for t in range(idx_s, idx_e))

    def book_charger(self, hub: Hub, start_min: int, end_min: int):
        idx_s = max(0, start_min - self.sim_start)
        idx_e = min(len(self.hub_occupancy[hub.id]), end_min - self.sim_start)
        for t in range(idx_s, idx_e):
            self.hub_occupancy[hub.id][t] += 1

    def release_charger(self, hub: Hub, start_min: int, end_min: int):
        idx_s = max(0, start_min - self.sim_start)
        idx_e = min(len(self.hub_occupancy[hub.id]), end_min - self.sim_start)
        for t in range(idx_s, idx_e):
            self.hub_occupancy[hub.id][t] = max(0, self.hub_occupancy[hub.id][t] - 1)

    def plan(self) -> Dict:
        start_ts = time.time()
        sorted_trips = sorted(self.trips, key=lambda t: t.start_time)
        hub = self.hubs[0]

        cab_state = {
            c.id: {
                "time": 960,
                "loc": c.current_location,
                "soc": c.initial_soc_kwh,
                "cab": c,
            }
            for c in self.cabs
        }

        for trip in sorted_trips:
            best_cab_id = None
            best_cost = float("inf")
            best_action = None
            reasons = []

            for c_id, state in cab_state.items():
                cab = state["cab"]
                dh_dist = state["loc"].distance_to(trip.start_loc)
                dh_time = int(math.ceil((dh_dist / cab.speed_kmh) * 60))
                arr_trip_start = state["time"] + dh_time

                if arr_trip_start <= trip.start_time:
                    dh_energy = dh_dist * cab.consumption_per_km
                    trip_energy = trip.distance_km * cab.consumption_per_km
                    ret_hub_dist = trip.end_loc.distance_to(hub.location)
                    ret_hub_energy = ret_hub_dist * cab.consumption_per_km

                    soc_at_start = state["soc"] - dh_energy
                    soc_after_trip = soc_at_start - trip_energy
                    soc_after_hub_reach = soc_after_trip - ret_hub_energy

                    if soc_at_start >= cab.min_floor_kwh and soc_after_hub_reach >= cab.min_floor_kwh:
                        cost = dh_dist + (trip.start_time - arr_trip_start) * 0.02
                        if cost < best_cost:
                            best_cost = cost
                            best_cab_id = c_id
                            best_action = ("DIRECT", dh_dist, dh_time, soc_at_start, soc_after_trip)
                    else:
                        reasons.append("LOW_SOC")
                else:
                    reasons.append("TIMING_CONFLICT")

            if best_cab_id is None:
                for c_id, state in cab_state.items():
                    cab = state["cab"]
                    d_to_hub = state["loc"].distance_to(hub.location)
                    t_to_hub = int(math.ceil((d_to_hub / cab.speed_kmh) * 60))
                    arr_hub_t = state["time"] + t_to_hub
                    e_to_hub = d_to_hub * cab.consumption_per_km
                    soc_arr_hub = state["soc"] - e_to_hub

                    if soc_arr_hub < cab.min_floor_kwh:
                        continue

                    d_hub_to_trip = hub.location.distance_to(trip.start_loc)
                    t_hub_to_trip = int(math.ceil((d_hub_to_trip / cab.speed_kmh) * 60))
                    dep_hub_t = trip.start_time - t_hub_to_trip

                    if dep_hub_t >= arr_hub_t + 15:
                        if self.can_book_charger(hub, arr_hub_t, dep_hub_t):
                            dur = dep_hub_t - arr_hub_t
                            e_added = self.curve.energy_added_in_minutes(
                                soc_arr_hub, dur, cab.battery_capacity_kwh, hub.charger_power_kw
                            )
                            soc_dep_hub = soc_arr_hub + e_added
                            soc_at_start = soc_dep_hub - (d_hub_to_trip * cab.consumption_per_km)
                            trip_energy = trip.distance_km * cab.consumption_per_km
                            soc_after_trip = soc_at_start - trip_energy
                            ret_hub = trip.end_loc.distance_to(hub.location) * cab.consumption_per_km

                            if soc_at_start >= cab.min_floor_kwh and (soc_after_trip - ret_hub) >= cab.min_floor_kwh:
                                charge_cost = e_added * hub.get_tariff((arr_hub_t + dep_hub_t) // 2)
                                cost = 40.0 + d_to_hub + d_hub_to_trip + charge_cost
                                if cost < best_cost:
                                    best_cost = cost
                                    best_cab_id = c_id
                                    best_action = (
                                        "CHARGE_THEN_TRIP", d_to_hub, arr_hub_t, dep_hub_t,
                                        e_added, charge_cost, d_hub_to_trip, soc_dep_hub,
                                        soc_at_start, soc_after_trip
                                    )

            if best_cab_id is not None:
                st = cab_state[best_cab_id]
                cab = st["cab"]
                trip.assigned_cab_id = best_cab_id
                self.assigned_trips.append(trip)

                if best_action[0] == "DIRECT":
                    _, dh_d, dh_t, soc_s, soc_e = best_action
                    if dh_d > 0.05:
                        cab.schedule.append(Activity(
                            act_type=ActivityType.EMPTY_DRIVE,
                            start_time=st["time"],
                            end_time=st["time"] + dh_t,
                            start_loc=st["loc"],
                            end_loc=trip.start_loc,
                            start_soc_kwh=st["soc"],
                            end_soc_kwh=soc_s,
                            ref_id=f"EMPTY_TO_{trip.id}"
                        ))
                    if trip.start_time > st["time"] + dh_t:
                        cab.schedule.append(Activity(
                            act_type=ActivityType.IDLE,
                            start_time=st["time"] + dh_t,
                            end_time=trip.start_time,
                            start_loc=trip.start_loc,
                            end_loc=trip.start_loc,
                            start_soc_kwh=soc_s,
                            end_soc_kwh=soc_s
                        ))
                    cab.schedule.append(Activity(
                        act_type=ActivityType.TRIP,
                        start_time=trip.start_time,
                        end_time=trip.end_time,
                        start_loc=trip.start_loc,
                        end_loc=trip.end_loc,
                        start_soc_kwh=soc_s,
                        end_soc_kwh=soc_e,
                        ref_id=trip.id
                    ))
                    st["time"] = trip.end_time
                    st["loc"] = trip.end_loc
                    st["soc"] = soc_e

                elif best_action[0] == "CHARGE_THEN_TRIP":
                    (_, d_to_h, arr_h, dep_h, e_add, chg_cost, d_h_to_t, soc_dep, soc_s, soc_e) = best_action
                    cab.schedule.append(Activity(
                        act_type=ActivityType.EMPTY_DRIVE,
                        start_time=st["time"],
                        end_time=arr_h,
                        start_loc=st["loc"],
                        end_loc=hub.location,
                        start_soc_kwh=st["soc"],
                        end_soc_kwh=st["soc"] - (d_to_h * cab.consumption_per_km),
                        ref_id="EMPTY_TO_HUB"
                    ))
                    self.book_charger(hub, arr_h, dep_h)
                    cab.schedule.append(Activity(
                        act_type=ActivityType.CHARGING,
                        start_time=arr_h,
                        end_time=dep_h,
                        start_loc=hub.location,
                        end_loc=hub.location,
                        start_soc_kwh=st["soc"] - (d_to_h * cab.consumption_per_km),
                        end_soc_kwh=soc_dep,
                        ref_id=hub.id,
                        cost=chg_cost
                    ))
                    cab.schedule.append(Activity(
                        act_type=ActivityType.EMPTY_DRIVE,
                        start_time=dep_h,
                        end_time=trip.start_time,
                        start_loc=hub.location,
                        end_loc=trip.start_loc,
                        start_soc_kwh=soc_dep,
                        end_soc_kwh=soc_s,
                        ref_id=f"EMPTY_TO_{trip.id}"
                    ))
                    cab.schedule.append(Activity(
                        act_type=ActivityType.TRIP,
                        start_time=trip.start_time,
                        end_time=trip.end_time,
                        start_loc=trip.start_loc,
                        end_loc=trip.end_loc,
                        start_soc_kwh=soc_s,
                        end_soc_kwh=soc_e,
                        ref_id=trip.id
                    ))
                    st["time"] = trip.end_time
                    st["loc"] = trip.end_loc
                    st["soc"] = soc_e
            else:
                if "LOW_SOC" in reasons and "TIMING_CONFLICT" not in reasons:
                    trip.backup_reason = "Nearby cabs lack charge (>15% floor) and hub chargers are congested"
                elif all(r == "TIMING_CONFLICT" for r in reasons):
                    trip.backup_reason = "All available cabs engaged in active trips; deadhead reach time exceeds start time"
                else:
                    trip.backup_reason = "Insufficient battery SoC on reachable cabs and insufficient idle time to reach hub & charge"
                self.backup_trips.append(trip)

        return {
            "elapsed_seconds": time.time() - start_ts,
            "assigned_count": len(self.assigned_trips),
            "backup_count": len(self.backup_trips),
        }
EOF
