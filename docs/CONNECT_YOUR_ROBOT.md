# Connect your own robot

How to bring a VDA 5050 robot (a real one, its simulator, or a ROS 2 stack behind a connector) into the ActuNode
lab and check how well it speaks VDA 5050. Written for robot vendors and integrators. About 15 minutes once the
robot can reach the lab's broker. Worked example: [CONFORMANCE_ROS2_CONNECTOR.md](CONFORMANCE_ROS2_CONNECTOR.md).

## 1. Start the lab and give the robot a login

```bash
docker compose up -d --build
docker compose run --rm mqtt-init add-robot <manufacturer> <serial>    # prints username and password
docker compose kill -s HUP mosquitto                                    # the broker loads the new login
```

The login is `<manufacturer>.<serial>`. It may publish only that robot's `state`, `connection`, `visualization` and
`factsheet`, and read only its own `order`, `instantActions`, `zoneSet` and `responses`
([D-28](DECISIONS.md)). It cannot see or command other robots.

## 2. Point the robot at the broker

| Setting | Value |
|---|---|
| Broker, on this computer | `localhost:1883` (plain MQTT) |
| Broker, from the network | `<lab host>:8883`, MQTT over TLS: start the lab in sharing mode (README, "Sharing the lab"), trust the lab's CA: `docker compose run --rm cert-init show ca > actunode-ca.crt` |
| Interface name | `uagv` |
| Topics | `uagv/v2/<manufacturer>/<serial>/...` (VDA 5050 2.x) or `uagv/v3/...` (3.0) |
| Map | ActuNode's warehouse map is called `warehouse`: 40 × 20 m, origin bottom-left, locations in `GET /api/locations` |

Connectors with their own settings: InOrbit's ROS 2 connector, for example, needs
`vda5050_protocol_version`, `interface_name`, `mqtt_username`/`mqtt_password`, and the CA in
`VDA5050_CONNECTOR_TLS_CA_CERT` (it always uses TLS with a login). See `ros2/entrypoint.sh` for a complete example.

Check: the robot appears in the UI's robot table (`<version>/<manufacturer>/<serial>`), and the Messages panel shows
its traffic with any validation issues next to each message.

## 3. Send it a mission

UI: Mission panel, **Target** = your robot's manufacturer and version. Or:

```bash
curl -s -X POST localhost:8080/api/missions -H 'content-type: application/json' \
  -d '{"robot_id":"<serial>","manufacturer":"<manufacturer>","vda_version":"2","destination":"STORAGE_A17","theta":1.57}'
```

The first node is where the robot reports itself (with its reported heading), the last is the location
(`theta` optional, radians). With a `source`, the order has a pick there and a drop at the destination
(`load_id` optional); without, it has no actions: a robot that cannot run pick/drop rejects the first kind.

## 4. Run the conformance suite

`conformance/vda5050-2/` checks VDA 5050 2.x behaviour any robot should have: online with a last will, state
messages valid against the official schema, header ids and timestamps, operating mode, position initialised,
orders without headings accepted (or rejected *with an error*), a mission driven to its node, `driving` while
moving, `cancelOrder`. Plain VDA 5050 fields only: no ActuNode extension.

```bash
cp -r conformance/vda5050-2 my-robot
sed -i 's/manufacturer: ROS2/manufacturer: <manufacturer>/; s/nav2_01/<serial>/g; s|/ROS2/|/<manufacturer>/|g' my-robot/*.yaml
python3 -m venv cli/.venv && cli/.venv/bin/pip install ./cli
cli/.venv/bin/actunode test my-robot --vda-version 2 --junit my-robot.xml
```

Each scenario is one check; a failure names the step and what the robot said instead. Locations used: PACK_SORT,
LOADING_DOCK_2, RECEIVING_DOOR_1, LOADING_DOCK_1 (scenarios 06–09 drive there; adjust if your robot cannot).

Orders the mission sender would never build (a node the robot cannot reach, a map it does not have) are in
`conformance/raw_checks.py`, sent with a fleet manager login:

```bash
docker compose run --rm mqtt-init add-master conformance <manufacturer>   # prints the password: save it to a file
docker compose kill -s HUP mosquitto
python3 conformance/raw_checks.py --password-file pw.txt --manufacturer <manufacturer> --serial <serial>
```

## 5. Investigate and share

- **Record** a run (Record button) and download the session: a colleague can upload, validate and replay it.
- **Validate offline**: the Validate button on a session lists every rule broken, with counts.
- **In CI**: `docker compose run --rm runner test my-robot/` ([examples/ci/](../examples/ci/README.md)).
- Robot topics carry your robot's data into the lab's recordings: keep recordings of customer sites private.

## What the lab cannot check

The lab sees what crosses the broker. It cannot see the robot's internal state, safety behaviour, or anything
reported only on the robot's own UI. Failure injection works only on ActuNode's simulated robots, never on yours.
