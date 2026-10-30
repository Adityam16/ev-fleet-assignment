cat << 'EOF' > src/models.py
from __future__ import annotations
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

class ActivityType(str, Enum):
    IDLE = "IDLE"
    EMPTY_DRIVE = "EMPTY_DRIVE"
    TRIP = "TRIP"
    CHARGING = "CHARGING"

@dataclass(frozen=True)
class Location:
    id: str
    x: float
    y: float

    def distance_to(self, other: Location) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

@dataclass
class Hub:
    id: str
    location: Location
    charger_count: int
    charger_power_kw: float
    peak_start_min: int = 1020  # 17:00
    peak_end_min: int = 1260    # 21:00
    peak_tariff_per_kwh: float = 0.28
    off_peak_tariff_per_kwh: float = 0.12

    def get_tariff(self, minute: int) -> float:
        if self.peak_start_min <= minute <= self.peak_end_min:
            return self.peak_tariff_per_kwh
        return self.off_peak_tariff_per_kwh

class ChargingCurveModel:
    def __init__(self, efficiency: float = 0.92, taper_fraction: float = 0.25):
        self.efficiency = efficiency
        self.taper_fraction = taper_fraction

    def charging_time_minutes(self, start_kwh: float, target_kwh: float, capacity_kwh: float, charger_power_kw: float) -> float:
        if target_kwh <= start_kwh:
            return 0.0
        split_kwh = 0.80 * capacity_kwh
        eff_fast = charger_power_kw * self.efficiency
        eff_slow = eff_fast * self.taper_fraction
        hours = 0.0
        if start_kwh < split_kwh:
            fast_part = min(target_kwh, split_kwh) - start_kwh
            hours += fast_part / eff_fast
        if target_kwh > split_kwh:
            slow_part = target_kwh - max(start_kwh, split_kwh)
            hours += slow_part / eff_slow
        return hours * 60.0

    def energy_added_in_minutes(self, start_kwh: float, duration_min: float, capacity_kwh: float, charger_power_kw: float) -> float:
        if duration_min <= 0:
            return 0.0
        split_kwh = 0.80 * capacity_kwh
        eff_fast = charger_power_kw * self.efficiency
        eff_slow = eff_fast * self.taper_fraction
        rem_hours = duration_min / 60.0
        current_kwh = start_kwh
        if current_kwh < split_kwh:
            time_to_80 = (split_kwh - current_kwh) / eff_fast
            if rem_hours <= time_to_80:
                return rem_hours * eff_fast
            current_kwh = split_kwh
            rem_hours -= time_to_80
        added_slow = rem_hours * eff_slow
        return min(capacity_kwh, current_kwh + added_slow) - start_kwh

@dataclass
class Trip:
    id: str
    start_loc: Location
    end_loc: Location
    start_time: int
    end_time: int
    distance_km: float
    latest_finish: int
    energy_kwh: float
    assigned_cab_id: Optional[str] = None
    backup_reason: Optional[str] = None

@dataclass
class Activity:
    act_type: ActivityType
    start_time: int
    end_time: int
    start_loc: Location
    end_loc: Location
    start_soc_kwh: float
    end_soc_kwh: float
    ref_id: Optional[str] = None
    cost: float = 0.0

@dataclass
class Vehicle:
    id: str
    battery_capacity_kwh: float
    initial_soc_kwh: float
    consumption_per_km: float
    current_location: Location
    speed_kmh: float = 35.0
    min_floor_fraction: float = 0.15
    schedule: List[Activity] = field(default_factory=list)

    @property
    def min_floor_kwh(self) -> float:
        return self.min_floor_fraction * self.battery_capacity_kwh
EOF
