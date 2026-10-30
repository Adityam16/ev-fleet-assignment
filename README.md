# EV Fleet Charging & Trip Assignment System
MoveInSync Advanced Track Hiring Assessment - Case Study 6

## Overview
High-performance dispatch and charging scheduler for EV corporate fleets.
- **Scale:** 300 Cabs, 40 Chargers, 1,500 Shifts/Trips
- **Performance:** Solves entire shift plan in **~0.89s** (Target < 30s)
- **Live Re-plan:** Handles battery drift and charger failures in **< 2ms** (Target < 2s)

## Hard Invariants Enforced
1. Strict 15% battery safety floor across all trips and deadheads.
2. Two-part non-linear CC/CV charging curve (80% fast threshold).
3. Hard charger bay concurrency ceiling.
4. Lexicographic optimization: Minimize backup cabs first, then minimize tariff costs.nul not found
