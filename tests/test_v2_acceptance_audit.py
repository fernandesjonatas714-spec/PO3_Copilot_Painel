import tempfile
import unittest
import os
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from pathlib import Path
from threading import Event

from po3.collection.mt5_m1_collector import CollectorConfig, collect_once, run_worker
from po3.collection.scheduler import next_boundary
from po3.v2_config import flags
from po3.storage.market_repository import acquire_lease, release_lease

class FakeMT5:
    TIMEFRAME_M1 = 1
    def __init__(self, rows, tick_time=None):
        self.rows = rows
        self.tick_time = tick_time
    def copy_rates_from_pos(self, *args): return self.rows
    def symbol_info_tick(self, symbol):
        return SimpleNamespace(time=int(self.tick_time.timestamp()), time_msc=int(self.tick_time.timestamp()*1000), bid=1.0, ask=1.0, last=1.0)

class V2AcceptanceAuditTests(unittest.TestCase):
    def setUp(self):
        import os
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.path = Path(path)
    def tearDown(self):
        try: self.path.unlink()
        except OSError: pass

    def test_flags_data_on_decision_off(self):
        f = flags()
        self.assertTrue(f["AUTO_DATA_COLLECTION"])
        self.assertTrue(f["MARKET_STATE_SNAPSHOT_ENABLED"])
        self.assertTrue(f["OUTCOME_TRACKING_ENABLED"])
        self.assertTrue(f["EVALUATION_ENGINE_ENABLED"])
        self.assertFalse(f["AUTO_DECISION_ENGINE"])
        self.assertFalse(f["MODEL_BENCHMARK_ENABLED"])

    def test_boundary_aligns_every_five_minutes(self):
        x = datetime(2026, 1, 1, 12, 3, 22, tzinfo=timezone.utc)
        self.assertEqual(next_boundary(x).minute, 5)
        x = datetime(2026, 1, 1, 12, 58, tzinfo=timezone.utc)
        self.assertEqual(next_boundary(x).hour, 13)
        self.assertEqual(next_boundary(x).minute, 0)

    def test_worker_one_cycle_persists_and_releases(self):
        now = datetime(2026,1,1,12,2,30,tzinfo=timezone.utc)
        row = {"time": int(datetime(2026,1,1,12,1,tzinfo=timezone.utc).timestamp()), "open":1, "high":2, "low":0, "close":1.5}
        mt5 = FakeMT5([row], now)
        from po3.collection.time_alignment import Mt5TimeAlignmentDetector
        detector = Mt5TimeAlignmentDetector()
        first = collect_once(CollectorConfig("WIN", str(self.path)), mt5, now_utc=now, alignment_detector=detector)
        self.assertEqual(first["status"], "UNAVAILABLE")
        mt5.tick_time = now + timedelta(seconds=10)
        second = collect_once(CollectorConfig("WIN", str(self.path)), mt5, now_utc=now + timedelta(seconds=10), alignment_detector=detector)
        self.assertEqual(second["status"], "OK")
        self.assertEqual(second["inserted"], 1)
        self.assertIsNotNone(acquire_lease("po3-m1","WIN",str(self.path),"second"))
        release_lease("po3-m1","WIN","second",str(self.path))

    def test_second_worker_rejected(self):
        owner=acquire_lease("po3-m1","WIN",str(self.path),"a")
        self.assertIsNotNone(owner)
        self.assertIsNone(acquire_lease("po3-m1","WIN",str(self.path),"b"))
        release_lease("po3-m1","WIN",owner,str(self.path))

    def test_run_worker_stop_event(self):
        stop=Event(); stop.set()
        run_worker(CollectorConfig("WIN",str(self.path)), FakeMT5([]), stop, max_cycles=1)

    def test_worker_stop_file_releases_lease(self):
        stop_path = self.path.with_suffix(".stop")
        stop_path.write_text("stop\n", encoding="ascii")
        old = os.environ.get("PO3_WORKER_STOP_FILE")
        os.environ["PO3_WORKER_STOP_FILE"] = str(stop_path)
        try:
            run_worker(CollectorConfig("WIN", str(self.path)), FakeMT5([]), max_cycles=2)
            import sqlite3
            with sqlite3.connect(self.path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM collector_leases").fetchone()[0], 0)
        finally:
            if old is None: os.environ.pop("PO3_WORKER_STOP_FILE", None)
            else: os.environ["PO3_WORKER_STOP_FILE"] = old
            stop_path.unlink(missing_ok=True)

if __name__ == "__main__":
    unittest.main()
