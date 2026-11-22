import datetime
import importlib.util
import json
import os
import pathlib
import random
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).parent.parent / "automations" / "preflight" / "wander_random.py"
spec = importlib.util.spec_from_file_location("wander_random", SCRIPT)
wr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wr)


def jst(hour, minute, day=22):
    return datetime.datetime(2026, 11, day, hour, minute, tzinfo=wr.JST)


class DrawSlots(unittest.TestCase):
    def test_slots_follow_the_rules(self):
        for seed in range(2000):
            slots = wr.draw_slots(jst(10, 0), None, random.Random(seed))
            self.assertLessEqual(len(slots), 3)
            self.assertEqual(slots, sorted(slots))
            for m in slots:
                self.assertEqual(m % wr.TICK, 0)
                self.assertTrue(0 <= m < 60)
            for a, b in zip(slots, slots[1:]):
                self.assertGreaterEqual(b - a, wr.MIN_GAP)

    def test_every_count_from_zero_to_three_occurs(self):
        counts = {len(wr.draw_slots(jst(10, 0), None, random.Random(seed))) for seed in range(500)}
        self.assertEqual(counts, {0, 1, 2, 3})

    def test_mean_runs_per_hour(self):
        n = 5000
        total = sum(len(wr.draw_slots(jst(10, 0), None, random.Random(seed))) for seed in range(n))
        self.assertAlmostEqual(total / n, 1.3, delta=0.1)

    def test_drawn_late_in_the_hour_starts_at_the_current_tick(self):
        for seed in range(500):
            slots = wr.draw_slots(jst(10, 42), None, random.Random(seed))
            self.assertTrue(all(m >= 40 for m in slots), slots)

    def test_keeps_gap_after_previous_run(self):
        last_run = jst(9, 55).timestamp()
        for seed in range(500):
            slots = wr.draw_slots(jst(10, 0), last_run, random.Random(seed))
            self.assertTrue(all(m >= 5 for m in slots), slots)


class Decide(unittest.TestCase):
    def test_new_hour_draws_slots_and_keeps_last_run(self):
        out, state = wr.decide(jst(10, 0), {"hour": "2026-11-22T09", "slots": [5], "last_run": 1.0}, random.Random(1))
        self.assertEqual(state["hour"], "2026-11-22T10")
        self.assertIn("slots", state)
        if not out["run"]:
            self.assertEqual(state["last_run"], 1.0)

    def test_runs_only_on_a_slot(self):
        state = {"hour": "2026-11-22T10", "slots": [15, 40], "last_run": None}
        out, state = wr.decide(jst(10, 10), state, random.Random(0))
        self.assertFalse(out["run"])
        self.assertIn("not a slot", out["reason"])
        self.assertIsNone(state["last_run"])
        out, state = wr.decide(jst(10, 17), state, random.Random(0))
        self.assertTrue(out["run"])
        self.assertEqual(state["last_run"], jst(10, 17).timestamp())
        self.assertEqual(state["slots"], [15, 40])

    def test_same_hour_does_not_redraw(self):
        state = {"hour": "2026-11-22T10", "slots": [], "last_run": None}
        for minute in range(0, 60, 5):
            out, state = wr.decide(jst(10, minute), state, random.Random(minute))
            self.assertFalse(out["run"])
            self.assertEqual(state["slots"], [])

    def test_whole_hour_runs_match_drawn_slots(self):
        state = {}
        runs = []
        for minute in range(0, 60, 5):
            out, state = wr.decide(jst(10, minute), state, random.Random(7))
            if out["run"]:
                runs.append(minute)
        self.assertEqual(runs, state["slots"])


class EventTime(unittest.TestCase):
    def test_window_start(self):
        self.assertEqual(wr.event_time({"payload": {"window_start": jst(13, 5).timestamp()}}), jst(13, 5))

    def test_numeric_received_at(self):
        self.assertEqual(wr.event_time({"received_at": jst(13, 5).timestamp()}), jst(13, 5))

    def test_iso_received_at(self):
        self.assertEqual(wr.event_time({"received_at": "2026-11-22T04:05:00Z"}), jst(13, 5))


class Main(unittest.TestCase):
    def run_script(self, tmp, event, state=None):
        paths = {k: os.path.join(tmp, k.lower()) for k in ("EVENT_FILE", "STATE_FILE", "OUTPUT_FILE")}
        with open(paths["EVENT_FILE"], "w") as f:
            json.dump(event, f)
        if state is not None:
            with open(paths["STATE_FILE"], "w") as f:
                json.dump(state, f)
        subprocess.run([sys.executable, str(SCRIPT)], env={**os.environ, **paths}, check=True)
        with open(paths["OUTPUT_FILE"]) as f, open(paths["STATE_FILE"]) as g:
            return json.load(f), json.load(g)

    def test_first_run_without_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, state = self.run_script(tmp, {"payload": {"window_start": jst(10, 0).timestamp()}})
            self.assertIn("run", out)
            self.assertEqual(state["hour"], "2026-11-22T10")

    def test_runs_on_slot_from_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {"hour": "2026-11-22T10", "slots": [20], "last_run": None}
            out, state = self.run_script(tmp, {"payload": {"window_start": jst(10, 20).timestamp()}}, state)
            self.assertEqual(out, {"run": True})
            self.assertEqual(state["last_run"], jst(10, 20).timestamp())

    def test_corrupt_state_is_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "state_file"), "w") as f:
                f.write("{not json")
            out, state = self.run_script(tmp, {"payload": {"window_start": jst(10, 0).timestamp()}})
            self.assertEqual(state["hour"], "2026-11-22T10")


if __name__ == "__main__":
    unittest.main()
