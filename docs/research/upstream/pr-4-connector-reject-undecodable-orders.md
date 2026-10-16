# PR draft for `inorbit-ai/ros_amr_interop`: reject orders that cannot be decoded instead of dropping them

Patch: [ros2/patches/ros_amr_interop/0003-report-undecodable-orders.patch](../../../ros2/patches/ros_amr_interop/0003-report-undecodable-orders.patch)
(against `de36489`, applies on its own; `mqtt_bridge.py`, `vda5050_controller.py`).

## Title

vda5050_connector: report orders that cannot be decoded as validationError instead of dropping them

## Description

When `mqtt_bridge` cannot convert an incoming order (a missing mandatory field such as `nodePosition.x`, or a value of
the wrong type), it logs `Ignoring invalid VDA5050 message: ...` and drops the order. Nothing reaches the state, so
the master control waits for a robot that will never act. VDA 5050 §6.1.1: "the expected behavior is to communicate
this within an error message and to reject the order"; the error type is `validationError` (§6.6.4.1).

Changes:

- `mqtt_bridge.py`: if decoding a message on the `order` topic raises `KeyError`, `ValueError` or `TypeError`, the
  bridge publishes a `vda5050_msgs/Error` on a new ROS topic, the order topic plus `_errors`: type
  `validationError`, level WARNING, description `order rejected: cannot decode: missing field 'x'` (or the
  exception text), with `orderId` and `orderUpdateId` in `errorReferences` when the message has them. The log line
  stays. Other topics behave as before.
- `vda5050_controller.py`: subscribes to that topic and adds the error to the state the same way `_reject_order`
  does (same lifecycle), publishing the state at once.

The controller types these errors with `OrderRejectErrors.VALIDATION_ERROR`, whose value is `"validationOrder"`
until the companion PR fixes it to `"validationError"`.

## Testing

ActuNode lab (https://github.com/Bahuncoder/ActuNode), `conformance/raw_checks.py`, check "an invalid order is
rejected with an error, not ignored" (an order whose target node has no `nodePosition.x`): before, `errors: []` and
the order silently ignored; after, the order is not taken and the state carries
`{"errorType": "validationError", "errorDescription": "order rejected: cannot decode: missing field 'x'",
"errorReferences": [{"referenceKey": "orderId", ...}, {"referenceKey": "orderUpdateId", ...}]}`.
The nine conformance scenarios still pass.
