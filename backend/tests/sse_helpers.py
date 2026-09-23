import json


def parse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for frame in body.strip().split("\n\n"):
        if not frame:
            continue
        name, data = frame.split("\n")
        assert name.startswith("event: ") and data.startswith("data: ")
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events
