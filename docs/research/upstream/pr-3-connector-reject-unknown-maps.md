# PR draft for `inorbit-ai/ros_amr_interop`: reject orders on unknown maps; fix the validationError type

Patch: [ros2/patches/ros_amr_interop/0002-reject-orders-on-unknown-maps.patch](../../../ros2/patches/ros_amr_interop/0002-reject-orders-on-unknown-maps.patch)
(applies after PR 2's patch, against `de36489`; one file, `vda5050_connector_py/vda5050_controller.py`).

## Title

vda5050_connector: optionally reject orders on maps the vehicle does not have; report validation errors as `validationError`

## Description

1. **Orders on unknown maps are accepted.** VDA 5050 2.1 §6.7.1: "Before accepting a new order, the vehicle shall
   check that there is a map ... for each map identifier". The connector accepts any `mapId`; Nav2 then retries the
   goal (about 24 s with default settings) and the order fails late. `order_msg_is_valid` is a stub
   (`# TODO: Proper implementation`) that always returns valid.
2. **Validation errors use a non-standard type.** `OrderRejectErrors.VALIDATION_ERROR = "validationOrder"`. The type
   VDA 5050 defines is `validationError`; a master control matching on it never sees these rejections.

Changes:

- New parameter `known_map_ids` (string array). Empty, the default, disables the check: existing deployments behave
  as before. When set, `order_msg_is_valid` rejects an order with any node on another map, through the existing
  `_reject_order` path: the order is not taken, and the state shows a WARNING `validationError` with `nodeId` and
  `mapId` in `errorReferences` (a new optional `references` argument to `_reject_order`).
- The default is `[""]` filtered to empty, because rclpy types an empty-list default as `BYTE_ARRAY` and then refuses
  a string list from the parameter file.
- `VALIDATION_ERROR = "validationError"`.

## Testing

In the ActuNode lab with `known_map_ids: ["map", "warehouse"]` and PRs 1 and 2: an order on `no_such_map` is
rejected immediately (`orderId` unchanged, `validationError` with `mapId: no_such_map`); all nine conformance
scenarios and all three raw checks pass, on repeated runs. Without the parameter, behaviour is unchanged.
