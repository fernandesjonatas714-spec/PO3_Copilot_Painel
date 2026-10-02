import unittest

from po3.launcher import _supervise_children


class FakeProcess:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class FakeStreamlit(FakeProcess):
    def __init__(self, alive_cycles):
        super().__init__(None)
        self.remaining = alive_cycles

    def poll(self):
        if self.remaining <= 0:
            return 0
        self.remaining -= 1
        return None


class LauncherSupervisionTests(unittest.TestCase):
    def _clock(self):
        value = [0.0]
        def now():
            return value[0]
        def sleep(seconds):
            value[0] += seconds
        return now, sleep

    def test_ai_crash_is_restarted_without_touching_streamlit(self):
        now, sleep = self._clock()
        streamlit = FakeStreamlit(14)
        children = {"ai_worker": FakeProcess(1)}
        created = []

        def spawn():
            created.append("ai")
            return FakeProcess(None)

        _supervise_children(streamlit, children, {"ai_worker": spawn}, lambda: False,
                            poll_interval=1, sleep_fn=sleep, clock=now)
        self.assertEqual(created, ["ai"])
        self.assertIsNone(children["ai_worker"].poll())

    def test_collector_crash_is_restarted(self):
        now, sleep = self._clock()
        streamlit = FakeStreamlit(8)
        children = {"worker": FakeProcess(1)}
        created = []
        _supervise_children(
            streamlit, children, {"worker": lambda: created.append(1) or FakeProcess(None)},
            lambda: False, poll_interval=1, sleep_fn=sleep, clock=now)
        self.assertEqual(len(created), 1)

    def test_intentional_shutdown_does_not_restart_children(self):
        now, sleep = self._clock()
        children = {"ai_worker": FakeProcess(1), "worker": FakeProcess(1)}
        created = []
        _supervise_children(
            FakeStreamlit(10), children,
            {"ai_worker": lambda: created.append("ai"), "worker": lambda: created.append("worker")},
            lambda: True, poll_interval=1, sleep_fn=sleep, clock=now)
        self.assertEqual(created, [])

    def test_streamlit_exit_does_not_restart_workers(self):
        now, sleep = self._clock()
        created = []
        _supervise_children(
            FakeStreamlit(0), {"ai_worker": FakeProcess(1)},
            {"ai_worker": lambda: created.append("ai")}, lambda: False,
            poll_interval=1, sleep_fn=sleep, clock=now)
        self.assertEqual(created, [])

    def test_crash_loop_uses_backoff(self):
        now, sleep = self._clock()
        created = []
        _supervise_children(
            FakeStreamlit(40), {"ai_worker": FakeProcess(1)},
            {"ai_worker": lambda: created.append(now()) or FakeProcess(1)}, lambda: False,
            poll_interval=1, sleep_fn=sleep, clock=now)
        self.assertEqual(created, [5.0, 15.0])


if __name__ == "__main__":
    unittest.main()
