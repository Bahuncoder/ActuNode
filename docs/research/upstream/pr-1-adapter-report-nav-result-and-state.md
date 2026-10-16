# PR draft for `inorbit-ai/vda5050_adapter_examples`: tb3 adapter reports Nav2's result and fills the VDA 5050 state

Patch: [ros2/patches/vda5050_adapter_examples/0001-tb3-adapter-report-state-and-nav-result.patch](../../../ros2/patches/vda5050_adapter_examples/0001-tb3-adapter-report-state-and-nav-result.patch)
(against `a7ad9a7`, one file, `vda5050_tb3_adapter/vda5050_tb3_adapter/tb3_adapter.py`).

## Title

tb3 adapter: report Nav2's real result; fill operatingMode, positionInitialized, driving and battery

## Description

The TurtleBot3 example is what most people copy when they write an adapter, so it is worth having it produce a
VDA 5050 state that passes the official JSON schema and tells the master control the truth about navigation.
Measured with the connector at `ros_amr_interop@de36489` (VDA 5050 2.0.0), Nav2 1.1.20 and `turtlebot3_fake_node`:

1. **Navigation failure reported as success.** `navigate_to_node_callback` calls `goal_handle.succeed()` whatever
   `NavigateToPose` returned. Send a node inside an obstacle: Nav2 aborts, and the state reports `lastNodeId` = that
   node, `errors: []`. VDA 5050 §6.10.6: `lastNodeId` is the "Node ID of last reached node". The connector already
   handles the failure correctly when told (`STATUS_ABORTED` → FATAL `noRouteError` "Failed to reach current node",
   `lastNodeId` unchanged); this change tells it.
2. **Stuck after a refused goal.** If Nav2 rejects the goal (e.g. an unknown frame), the response callback returns
   without clearing `_driving`, the execute callback waits forever, and the robot refuses every later order
   (`orderUpdateError`) until restarted.
3. **`operatingMode` is ""** in every state: not one of the five allowed values (§6.10.6), so every state fails the
   schema.
4. **`agvPosition.positionInitialized` is always false**, although the position comes from TF and is correct.
5. **`driving` is always false** (kept in `_driving`, never reported).
6. **`batteryState` is never filled**: `batteryCharge: 0.0`, which reads as an empty battery.

Changes:

- Store Nav2's terminal status; `succeed()` on SUCCEEDED, `canceled()` on CANCELED, `abort()` otherwise. A rejected
  goal counts as aborted and clears `_driving`.
- State: `operating_mode = AUTOMATIC`, `driving = self._driving`, `position_initialized = True` after the first
  successful map→base_link lookup, battery from a `battery_charge` parameter (default 100.0, `charging: false`;
  the fake TurtleBot3 has no battery, a real adapter reports its own).
- If the node's `theta` is NaN (not given; see the companion connector PR), face the direction of travel.
  Harmless without that PR: the connector never sends NaN today.

## Testing

In the ActuNode lab (https://github.com/Bahuncoder/ActuNode, `docker compose --profile ros2 up`, then the VDA 5050
2.x conformance suite `conformance/vda5050-2/` and `conformance/raw_checks.py`), both patches together:

| | Before | After |
|---|---|---|
| Conformance scenarios (9) | 4 pass | 9 pass |
| Unreachable node not reported reached / reported as an error | fail / fail | pass / pass (`noRouteError`) |
| Two raw-check runs back to back | second run stuck | both pass |

The unknown-map check still fails (map management is VDA 5050 2.1; the connector speaks 2.0). Report:
`docs/CONFORMANCE_ROS2_CONNECTOR.md` in that repository.
