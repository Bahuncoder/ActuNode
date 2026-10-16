# Upstream reports: InOrbit's VDA 5050 connector

Issue drafts for `inorbit-ai/ros_amr_interop` (and `vda5050_adapter_examples`), from the conformance report
([../../CONFORMANCE_ROS2_CONNECTOR.md](../../CONFORMANCE_ROS2_CONNECTOR.md)). Not filed yet: filing is the
founder's call. Each draft is self-contained: setup, steps, expected (with the VDA 5050 clause), actual.

| Draft | Repository | Severity for a fleet manager |
|---|---|---|
| [01-navigation-failure-reported-as-reached.md](01-navigation-failure-reported-as-reached.md) | vda5050_adapter_examples / ros_amr_interop | High |
| [02-order-without-theta-silently-ignored.md](02-order-without-theta-silently-ignored.md) | ros_amr_interop | High |
| [03-driving-always-false.md](03-driving-always-false.md) | ros_amr_interop | Medium |
| [04-operating-mode-and-position-initialized.md](04-operating-mode-and-position-initialized.md) | ros_amr_interop | Medium |
| [05-mqtt-bridge-typeerror-on-refused-connection.md](05-mqtt-bridge-typeerror-on-refused-connection.md) | ros_amr_interop | Low |
