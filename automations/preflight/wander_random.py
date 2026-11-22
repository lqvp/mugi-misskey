# Preflight check for the "TL 巡回" Automation (see automations/README.md).
# The trigger fires every 5 minutes, 09:00-23:55 Asia/Tokyo. At the first tick
# of each hour this draws 0-3 run slots (5-minute granularity, >=10 min apart,
# and >=10 min after the previous run) and lets the run through only on them.
import datetime
import json
import os
import random

JST = datetime.timezone(datetime.timedelta(hours=9))
WEIGHTS = [(0, 20), (1, 40), (2, 30), (3, 10)]  # runs per hour, mean 1.3
MIN_GAP = 10  # minutes
TICK = 5  # minutes, must match the trigger's BYMINUTE step


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def event_time(event):
    payload = event.get("payload") or {}
    ts = payload.get("window_start") or payload.get("scheduled_at")
    if isinstance(ts, (int, float)):
        return datetime.datetime.fromtimestamp(ts, JST)
    raw = event.get("received_at")
    if isinstance(raw, (int, float)):
        return datetime.datetime.fromtimestamp(raw, JST)
    if raw:
        return datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(JST)
    return datetime.datetime.now(JST)


def draw_slots(now, last_run, rng):
    """Pick this hour's run minutes, from the current tick to the end of the hour."""
    k = rng.choices([w[0] for w in WEIGHTS], [w[1] for w in WEIGHTS])[0]
    minute = (now.minute // TICK) * TICK
    candidates = list(range(minute, 60, TICK))
    if last_run:
        hour_start = now.replace(minute=0, second=0, microsecond=0).timestamp()
        candidates = [m for m in candidates if hour_start + m * 60 - last_run >= MIN_GAP * 60]
    rng.shuffle(candidates)
    slots = []
    for m in candidates:
        if len(slots) >= k:
            break
        if all(abs(m - s) >= MIN_GAP for s in slots):
            slots.append(m)
    return sorted(slots)


def decide(now, state, rng):
    """Return (output, new_state) for one tick."""
    minute = (now.minute // TICK) * TICK
    hour_key = now.strftime("%Y-%m-%dT%H")
    last_run = state.get("last_run")  # epoch seconds
    if state.get("hour") != hour_key or "slots" not in state:
        state = {"hour": hour_key, "slots": draw_slots(now, last_run, rng), "last_run": last_run}
    else:
        state = dict(state)
    if minute in state["slots"]:
        state["last_run"] = now.timestamp()
        return {"run": True}, state
    return {"run": False, "reason": f"not a slot ({hour_key} slots={state['slots']}, now={minute})"}, state


def main():
    event = load(os.environ["EVENT_FILE"], {})
    state = load(os.environ.get("STATE_FILE", ""), {})
    out, state = decide(event_time(event), state, random.Random())
    with open(os.environ["STATE_FILE"], "w") as f:
        json.dump(state, f)
    with open(os.environ["OUTPUT_FILE"], "w") as f:
        json.dump(out, f)


if __name__ == "__main__":
    main()
