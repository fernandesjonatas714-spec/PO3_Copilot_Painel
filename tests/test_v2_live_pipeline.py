import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from threading import Event
from po3.collection.mt5_m1_collector import CollectorConfig, run_worker
from po3.storage.market_repository import list_states, get_outcomes, get_m1_range

class FakeMT5:
    TIMEFRAME_M1=1
    def __init__(self, row): self.row=row
    def copy_rates_from_pos(self,*args):
        return [self.row]

class LivePipelineUnitTests(unittest.TestCase):
    def test_m1_to_marketstate_to_outcome_pipeline(self):
        import os
        fd,p=tempfile.mkstemp(suffix=".sqlite"); os.close(fd); db=Path(p)
        now=datetime.now(timezone.utc)
        row={"time":int((now-timedelta(minutes=2)).timestamp()),"open":100,"high":101,"low":99,"close":100.5}
        snap=SimpleNamespace(symbol="WIN",as_of=now,last_price=100.5,connected=True,source="fake",bars={"M1":[{"time":now-timedelta(minutes=2),"open":100,"high":101,"low":99,"close":100.5}]},levels={},zones={},events=[],notes=[],account={},macro={})
        def provider(cutoff): return snap, {"calendar":{"available":False},"news":{"headlines":[],"statuses":[]}}
        run_worker(CollectorConfig("WIN",str(db),poll_seconds=1),FakeMT5(row),Event(),max_cycles=1,snapshot_provider=provider)
        states=list_states(str(db),"WIN")
        self.assertEqual(len(states),1)
        self.assertIn(states[0]["cutoff_at_utc"], states[0]["state_json"])
        self.assertEqual(len(get_outcomes(str(db),states[0]["id"])),4)
        try: db.unlink()
        except OSError: pass

if __name__=="__main__": unittest.main()
