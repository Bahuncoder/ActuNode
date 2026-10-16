# PR draft for `inorbit-ai/ros_amr_interop`: nodePosition.theta is optional

Patch: [ros2/patches/ros_amr_interop/0001-theta-optional.patch](../../../ros2/patches/ros_amr_interop/0001-theta-optional.patch)
(against `de36489`, `humble-devel`; three files in `vda5050_connector/vda5050_connector_py/`).

## Title

vda5050_connector: accept orders whose nodePosition has no theta

## Description

VDA 5050 makes `nodePosition.theta` optional ("Optional: vehicle can plan the path by itself", §6.6.6 in 2.1; the
same in 2.0). `mqtt_bridge.generate_vda_order_msg` reads it as mandatory, so an order without it raises `KeyError`,
which is logged as `Ignoring invalid VDA5050 message: 'theta'` and the order is dropped: nothing in the state tells
the master control (see the companion issue on rejecting invalid orders).

Changes:

- `mqtt_bridge.py`: `x` and `y` stay required; a missing or null `theta` becomes NaN ("not given") in
  `NodePosition`, whose `theta` is a float.
- `vda5050_controller.py`: order stitching compares positions with `==`; NaN never equals NaN, so a stitched order
  without `theta` would fail. Two "not given" headings now count as equal (`math.isnan`).
- `utils.py`: `convert_ros_message_to_json` omits NaN fields (`json.dumps` would write a bare `NaN`, which is not
  JSON), so `nodeStates` echo the node without `theta`, as received.

Adapters decide what "no heading" means; the companion PR to `vda5050_adapter_examples` makes the TurtleBot3
example face the direction of travel.

## Testing

ActuNode conformance scenario `06_order_without_heading.yaml`: before, the order is dropped; after, the robot drives
to the node and reports it reached. All nine scenarios pass with both PRs (details in the adapter PR).
