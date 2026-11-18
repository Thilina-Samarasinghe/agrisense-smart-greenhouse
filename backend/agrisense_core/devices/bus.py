"""In-process publish/subscribe bus using MQTT topic semantics (`+` and `#` wildcards).

Swapping this for a real MQTT client (paho-mqtt) later keeps every topic and payload unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

Handler = Callable[[str, dict[str, Any]], None]


def topic_matches(pattern: str, topic: str) -> bool:
    return _match(pattern.split("/"), topic.split("/"))


def _match(p_parts: list[str], t_parts: list[str]) -> bool:
    for i, p in enumerate(p_parts):
        if p == "#":
            return True
        if i >= len(t_parts):
            return False
        if p not in ("+", t_parts[i]):
            return False
    return len(p_parts) == len(t_parts)


class MessageBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._parts: dict[str, list[str]] = {}
        self.retained: dict[str, dict[str, Any]] = {}

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self._subs[pattern].append(handler)
        self._parts[pattern] = pattern.split("/")
        for topic, payload in list(self.retained.items()):
            if topic_matches(pattern, topic):
                handler(topic, payload)

    def publish(self, topic: str, payload: dict[str, Any], retain: bool = True) -> None:
        if retain:
            self.retained[topic] = payload
        t_parts = topic.split("/")
        for pattern, handlers in list(self._subs.items()):
            if _match(self._parts[pattern], t_parts):
                for h in list(handlers):
                    h(topic, payload)
