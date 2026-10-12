"""Instant actions (2.1 section 6.8.1, 3.0 section 6.2.1): dispatch, caps, duplicate-id refusal and the handlers.

A mixin of Robot: the handlers change the robot's mission state, so they live next to it, not in a copy of it.
"""

import logging

from simulator.protocol import (
    CANCELLED,
    DONE,
    MAX_ID_LENGTH,
    MAX_INSTANT_ACTION_STATES,
    MAX_INSTANT_ACTIONS_PER_MESSAGE,
    PENDING,
    parse,
    ref,
)
from simulator.validation import check_actions, check_parameters, long_id

log = logging.getLogger(__name__)

ID_IN_USE = "actionId already in use"


class InstantActions:
    def handle_instant_actions_payload(self, payload: bytes) -> bool:
        """Apply a raw instantActions message. False if it is malformed and was ignored: neither version names
        an error for a message that cannot be parsed, so the caller only logs it."""
        message, why = parse(payload)
        if why:
            log.warning("%s: ignored instantActions message: %s", self.robot_id, why)
            return False
        actions = self._usable_instant_actions(message)
        if actions is None:
            return False
        if self.v.invalid_instant_action:
            # "Until new instant action is accepted" (3.0 section 6.6.7).
            self._drop_errors(self.v.invalid_instant_action)
        invalid = [action["actionId"] for action in actions if not self._perform_instant_action(action)]
        if invalid and self.v.invalid_instant_action:
            # One error per message, so a flood of bad actions cannot blow up the state message.
            self._add_error(
                self.v.invalid_instant_action, "invalid instant action", [ref("actionId", i) for i in invalid]
            )
        return True

    def _usable_instant_actions(self, message) -> list[dict] | None:
        """The actions of the message that can be answered, capped; None if the message has no valid action list."""
        actions = message.get("actions") if isinstance(message, dict) else None
        if not isinstance(actions, list):
            return None
        # An action whose id or type is too long cannot be answered safely (its state would echo it): ignore it.
        kept = [a for a in actions if not (isinstance(a, dict) and long_id(a, ("actionType", "actionId"), ""))]
        if len(kept) < len(actions):
            log.warning(
                "%s: ignored %d instant actions with an actionId or actionType over %d characters",
                self.robot_id,
                len(actions) - len(kept),
                MAX_ID_LENGTH,
            )
        # actionParameters are checked per action later: a bad one fails that action, not the message.
        if check_actions(kept, "actions", parameters=False):
            return None
        if len(kept) > MAX_INSTANT_ACTIONS_PER_MESSAGE:
            # Neither spec names an error for this: the extra actions are dropped and only logged.
            log.warning(
                "%s: ignored %d instant actions beyond the first %d of the message",
                self.robot_id,
                len(kept) - MAX_INSTANT_ACTIONS_PER_MESSAGE,
                MAX_INSTANT_ACTIONS_PER_MESSAGE,
            )
            kept = kept[:MAX_INSTANT_ACTIONS_PER_MESSAGE]
        return kept

    def _perform_instant_action(self, action: dict) -> bool:
        """Record the action's state and run it; False if it failed (the state says why)."""
        if action["actionType"] == "stateRequest":
            # The loop publishes when this is set; the event signature alone would miss a repeated request
            # with the same actionId (also one refused for reusing an id).
            self.state_requested = True
        in_use = self._id_in_use(action["actionId"])
        state = self._add_instant_state(action)
        if in_use:
            failure = ID_IN_USE
        elif action["actionType"] not in self.v.instant_actions:
            failure = f"unsupported instant action {action['actionType']!r}"
        elif "actionParameters" in action and check_parameters(action["actionParameters"], "actionParameters"):
            # Same outcome as an unknown action (3.0 names no error for bad parameters): FAILED.
            failure = "actionParameters must be a list of objects with a string key"
        else:
            self.INSTANT_HANDLERS[action["actionType"]](self, action, state)
            return True
        # 2.1 names no error for a failed instant action: only the FAILED action state reports it.
        self._set_status(state, "FAILED", failure)
        return False

    def _id_in_use(self, action_id: str) -> bool:
        return any(a["actionId"] == action_id for a in (*self.action_states, *self.instant_action_states))

    def _add_instant_state(self, action: dict) -> dict:
        state = {"actionId": action["actionId"], "actionType": action["actionType"], "actionStatus": "WAITING"}
        if len(self.instant_action_states) >= MAX_INSTANT_ACTION_STATES:
            self.drop_oldest_done_instant_state()
        self.instant_action_states.append(state)
        return state

    def drop_oldest_done_instant_state(self) -> bool:
        old = next((a for a in self.instant_action_states if a["actionStatus"] in DONE), None)
        if old:
            self.instant_action_states = [a for a in self.instant_action_states if a is not old]
        return old is not None

    def _cancel_order(self, action: dict, state: dict) -> None:
        wanted = next(
            (
                p.get("value")
                for p in action.get("actionParameters") or []
                if isinstance(p, dict) and p.get("key") == "orderId"
            ),
            None,
        )
        # 3.0 section 6.1.3.2: idle, or another orderId than the active one: FAILED. 2.1 has no such parameter.
        other_order = self.v.cancel_has_order_param and wanted is not None and wanted != self.order_id
        if self.idle or other_order:
            self._set_status(state, "FAILED", "no active order to cancel")
            self._drop_errors(self.v.no_order_to_cancel)
            self._add_error(
                self.v.no_order_to_cancel, "no active order to cancel", [ref("actionId", action["actionId"])]
            )
            return
        # Everything is instant, so the robot stops at once and is CANCELLED until a new order is accepted. Errors
        # other than a blocked path stay: they persist until a new order is accepted.
        self.mission_status = CANCELLED
        self.velocity = 0.0
        self.node_states = []
        self.edge_states = []
        self._drop_errors("pathBlocked")
        for order_action in self.action_states:
            if order_action["actionStatus"] in PENDING:
                self._set_status(order_action, "FAILED", "order cancelled")
        self._set_status(state, "FINISHED")

    def _start_pause(self, action: dict, state: dict) -> None:
        # Idempotent: pausing a paused robot (and resuming a running one) is not an error in either version.
        self.paused = True
        self._set_status(state, "FINISHED")

    def _stop_pause(self, action: dict, state: dict) -> None:
        self.paused = False
        self._set_status(state, "FINISHED")

    def _state_request(self, action: dict, state: dict) -> None:
        self._set_status(state, "FINISHED")

    def _factsheet_request(self, action: dict, state: dict) -> None:
        self.factsheet_requested = True
        self._set_status(state, "FINISHED")

    def _clear_instant_actions(self, action: dict, state: dict) -> None:
        # 3.0 removes finished/failed instant actions. This action's own state stays (FINISHED), so the
        # master can see that it worked; the next clear removes it.
        self.instant_action_states = [
            a for a in self.instant_action_states if a is state or a["actionStatus"] not in DONE
        ]
        self._set_status(state, "FINISHED")

    # Which handler performs which actionType; what a version supports is VersionProfile.instant_actions.
    INSTANT_HANDLERS = {
        "cancelOrder": _cancel_order,
        "startPause": _start_pause,
        "stopPause": _stop_pause,
        "stateRequest": _state_request,
        "factsheetRequest": _factsheet_request,
        "clearInstantActions": _clear_instant_actions,
    }
