"""A stack and a clock for runner tests: robots change state as fake time passes, no network involved."""

from actunode.client import RequestFailed, StackError


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def robot(robot_id="robot_01", status="IDLE", order="", errors=(), connection="ONLINE", vda="2", seen="T1"):
    return {
        "key": f"v{vda}/ActuNode/{robot_id}",
        "robotId": robot_id,
        "vdaMajor": f"v{vda}",  # as the API reports it (contracts/live_message_event.json)
        "manufacturer": "ActuNode",
        "connection": connection,
        "lastSeen": seen,
        "state": {
            "orderId": order,
            "errors": [{"errorType": t, "errorLevel": level} for t, level in errors],
            "actunode": {"missionStatus": status, "injectedFailures": []},
        },
    }


class FakeStack:
    """`timeline` is a list of (from_time, robots) pairs: the robot list the stack reports from that time on."""

    def __init__(self, clock: Clock, timeline=None, validation=None, messages=()):
        self.clock = clock
        self.timeline = timeline or [(0, [robot()])]
        self.validations = validation or [(0, {"epoch": 1, "byRule": []})]
        self.calls: list[tuple] = []
        self.refuse: dict[str, RequestFailed] = {}  # call name -> error to raise
        self.down = False
        self.messages = list(messages)  # (arrival time, {"topic": ..., "payload": ...})
        self.feed_error = None
        self.lab_calls: list[tuple] = []
        self.orders_sent = 0

    def _at(self, series):
        current = series[0][1]
        for start, value in series:
            if self.clock.now >= start:
                current = value
        return current

    def _call(self, name, *args):
        if self.down:
            raise StackError("connection refused")
        self.calls.append((name, *args))
        if name in self.refuse:
            raise self.refuse[name]

    def _lab(self, name, *args):
        """Recording and the live feed: kept apart from `calls`, which lists the robot commands."""
        if self.down:
            raise StackError("connection refused")
        self.lab_calls.append((name, *args))
        if name in self.refuse:
            raise self.refuse[name]

    def robots(self):
        if self.down:
            raise StackError("connection refused")
        return self._at(self.timeline)

    def validation(self):
        if self.down:
            raise StackError("connection refused")
        return self._at(self.validations)

    def send_mission(self, body):
        self._call("send_mission", body)
        self.orders_sent += 1
        return {"order_id": f"order-{self.orders_sent}"}

    def cancel_mission(self, robot_id, vda_version):
        self._call("cancel_mission", robot_id, vda_version)
        return {}

    def start_recording(self, name):
        self._lab("start_recording", name)
        return {"sessionId": f"20261013-120000_{name}"}

    def stop_recording(self):
        self._lab("stop_recording")
        return {}

    def open_feed(self, clock):
        self._lab("open_feed")
        return FakeFeed(self)

    def failure(self, robot_id, failure, action, params=None):
        self._call("failure", robot_id, failure, action, params)
        return {}


class FakeFeed:
    """Messages "arrive" at their timestamps: a message is visible once the fake clock has reached it."""

    def __init__(self, stack: FakeStack):
        self.stack = stack
        self.closed = False

    def since(self, start):
        if self.stack.feed_error:
            raise StackError(self.stack.feed_error)
        now = self.stack.clock.now
        return [message for at, message in self.stack.messages if start <= at <= now]

    def close(self):
        self.closed = True
