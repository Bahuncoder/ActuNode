"""What ActuNode has sent per robot, so an update can resend the nodes unchanged (3.0 wants that).

Memory only and capped (least recently used dropped) so made-up serials cannot grow it without bound.
What the robot is actually running comes from its own state, never from this memory (D-35).

`lock` is re-entrant and every method takes it, but that alone does not make an extend safe: the caller
holds `lock` from reading the robot's state to recording the update, so two extends cannot both send N+1.
"""

import threading
import time
from collections import OrderedDict

MAX_REMEMBERED_ORDERS = 1000  # robot keys ("<major>/<manufacturer>/<serial>")
MAX_ORDERS_PER_ROBOT = 10
MAX_NODES_PER_ORDER = 200


class SentOrders:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self._orders: OrderedDict[str, OrderedDict[str, dict]] = OrderedDict()

    def clear(self) -> None:
        with self.lock:
            self._orders.clear()

    def get(self, key: str, order_id: str) -> dict | None:
        """{"nodes": {sequenceId: node}, "last_sent_update_id": int, "sent_at": clock() of that send}."""
        with self.lock:
            return self._orders.get(key, {}).get(order_id)

    @staticmethod
    def is_full(entry: dict) -> bool:
        """No room to add another node to this order."""
        return len(entry["nodes"]) >= MAX_NODES_PER_ORDER

    def remember(self, key: str, order: dict, running: str | None = None) -> None:
        """Record an order or update just sent. `running` is the orderId the robot reports now: it is
        never the one dropped when the per-robot cap is hit."""
        with self.lock:
            orders = self._orders.setdefault(key, OrderedDict())
            entry = orders.setdefault(order["orderId"], {"nodes": {}, "last_sent_update_id": 0, "sent_at": 0.0})
            entry["nodes"].update({n["sequenceId"]: n for n in order["nodes"]})
            entry["last_sent_update_id"] = order["orderUpdateId"]
            entry["sent_at"] = self.clock()
            orders.move_to_end(order["orderId"])
            while len(orders) > MAX_ORDERS_PER_ROBOT:
                oldest = next((o for o in orders if o != running and o != order["orderId"]), None)
                if oldest is None:
                    break
                del orders[oldest]
            self._orders.move_to_end(key)
            while len(self._orders) > MAX_REMEMBERED_ORDERS:
                self._orders.popitem(last=False)


sent_orders = SentOrders()
