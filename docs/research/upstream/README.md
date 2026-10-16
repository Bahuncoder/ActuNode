# Upstream reports: InOrbit's VDA 5050 connector and example adapter

Drafts for `inorbit-ai/ros_amr_interop` (the connector) and `inorbit-ai/vda5050_adapter_examples` (the TurtleBot3
example adapter), from the conformance report ([../../CONFORMANCE_ROS2_CONNECTOR.md](../../CONFORMANCE_ROS2_CONNECTOR.md)).
**Not filed yet: filing is the founder's call** (it is public, under their GitHub account).

Most failures turned out to be in the example adapter, not the connector (D-55). Where we have a tested fix, we
propose a pull request rather than an issue; the patches are in [ros2/patches/](../../../ros2/patches/README.md) and
run in the lab with `ACTUNODE_ROS2_PATCHES=1`.

## Pull requests (tested together: 9/9 scenarios, 4/4 raw checks; each also applies on its own)

| Draft | Repository | Fixes |
|---|---|---|
| [pr-1-adapter-report-nav-result-and-state.md](pr-1-adapter-report-nav-result-and-state.md) | vda5050_adapter_examples | 01, 03, 04 below; stuck after a refused goal |
| [pr-2-connector-theta-optional.md](pr-2-connector-theta-optional.md) | ros_amr_interop | The `theta` part of 02 |
| [pr-3-connector-reject-unknown-maps.md](pr-3-connector-reject-unknown-maps.md) | ros_amr_interop | Orders on unknown maps (2.1 §6.7.1, opt-in); `validationOrder` → `validationError` |
| [pr-4-connector-reject-undecodable-orders.md](pr-4-connector-reject-undecodable-orders.md) | ros_amr_interop | The rest of 02: an order that cannot be decoded is rejected with `validationError`, not dropped |
| [pr-5-connector-refused-connection-log.md](pr-5-connector-refused-connection-log.md) | ros_amr_interop | 05 |

## Issue drafts (the evidence behind the PRs; every one is fixed by a PR)

| Draft | Repository | Severity for a fleet manager | Status |
|---|---|---|---|
| [01-navigation-failure-reported-as-reached.md](01-navigation-failure-reported-as-reached.md) | vda5050_adapter_examples | High | Fixed by PR 1; file only if the PR is not wanted |
| [02-order-without-theta-silently-ignored.md](02-order-without-theta-silently-ignored.md) | ros_amr_interop | High | Fixed by PRs 2 and 4 |
| [03-driving-always-false.md](03-driving-always-false.md) | vda5050_adapter_examples | Medium | Fixed by PR 1 |
| [04-operating-mode-and-position-initialized.md](04-operating-mode-and-position-initialized.md) | vda5050_adapter_examples | Medium | Fixed by PR 1 |
| [05-mqtt-bridge-typeerror-on-refused-connection.md](05-mqtt-bridge-typeerror-on-refused-connection.md) | ros_amr_interop | Low | Fixed by PR 5 |

Each PR is independent of the others (all apply to the current `humble-devel`); PR 1 and PR 4 refer to their
companions.
