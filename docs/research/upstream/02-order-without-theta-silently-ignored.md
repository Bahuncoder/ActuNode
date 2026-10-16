# An order without nodePosition.theta is silently ignored

**Setup.** `ros_amr_interop` at `de36489` (humble-devel), `vda5050_adapter_examples` at `a7ad9a7`, ROS 2 Humble, Nav2 1.1.20, `turtlebot3_fake_node`, Mosquitto 2.1 over TLS; `vda5050_protocol_version: 2.0.0`. Reproducible with the ActuNode lab (`docker compose --profile ros2 up`), https://github.com/Bahuncoder/ActuNode.

**Steps.** Send a valid order whose nodes have `nodePosition` without `theta`.

**Expected.** `theta` is optional ("Optional: vehicle can plan the path by itself", §6.6.6). If the robot cannot
accept the order it must reject it and say so: `validationError` (§6.6.4.1) in the state's `errors`; "the
expected behavior is to communicate this within an error message and to reject the order" (§6.1.1).

**Actual.** `mqtt_bridge` logs `Ignoring invalid VDA5050 message: 'theta'` (a `KeyError` during
deserialisation). The order is not taken, and the state shows no error.

**Suggested fix.** Treat `theta` as optional in the deserialiser (PR 2 does this). The general problem remains
after it: any order the bridge cannot deserialise is dropped with a log line, and `order_msg_is_valid` is a stub
that accepts everything. A rejected order should appear in the state as `validationError` (with the offending field
in `errorReferences`) instead of disappearing.
