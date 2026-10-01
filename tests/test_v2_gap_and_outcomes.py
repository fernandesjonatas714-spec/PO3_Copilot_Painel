import tempfile
import unittest
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
from pathlib import Path
from po3.collection.mt5_m1_collector import CollectorConfig, collect_once
from po3.storage.market_repository import insert_m1_bars, acquire_lease, get_m1_range, release_lease
from po3.outcome_engine import calculate_outcomes

class Fake:
    TIMEFRAME_M1=1
    def __init__(self, rows, tick_time): self.rows=rows; self.tick_time=tick_time
    def copy_rates_from_pos(self,*args): return self.rows
    def symbol_info_tick(self, symbol):
        return SimpleNamespace(time=int(self.tick_time.timestamp()), time_msc=int(self.tick_time.timestamp()*1000), bid=1.0, ask=1.0, last=1.0)

class V2GapOutcomeTests(unittest.TestCase):
    def setUp(self):
        import os
        fd,p=tempfile.mkstemp(suffix=".sqlite"); os.close(fd); self.db=Path(p)
    def tearDown(self):
        try:self.db.unlink()
        except OSError:pass
    def test_gap_recovery_and_restart_are_idempotent(self):
        base=datetime(2026,1,1,10,26,tzinfo=timezone.utc)
        rows=[{"time":int((base+timedelta(minutes=i)).timestamp()),"open":1+i,"high":2+i,"low":i,"close":1.5+i} for i in range(5)]
        mt5=Fake(rows,datetime(2026,1,1,10,31,30,tzinfo=timezone.utc))
        from po3.collection.time_alignment import Mt5TimeAlignmentDetector
        detector=Mt5TimeAlignmentDetector()
        first=collect_once(CollectorConfig("WIN",str(self.db)),mt5,now_utc=datetime(2026,1,1,10,31,30,tzinfo=timezone.utc),alignment_detector=detector)
        self.assertEqual(first["inserted"],0)
        mt5.tick_time=datetime(2026,1,1,10,31,40,tzinfo=timezone.utc)
        result=collect_once(CollectorConfig("WIN",str(self.db)),mt5,now_utc=mt5.tick_time,alignment_detector=detector)
        self.assertEqual(result["inserted"],5)
        mt5.tick_time=datetime(2026,1,1,10,31,50,tzinfo=timezone.utc)
        again=collect_once(CollectorConfig("WIN",str(self.db)),mt5,now_utc=mt5.tick_time,alignment_detector=detector)
        self.assertEqual(again["inserted"],0)
        self.assertEqual(len(get_m1_range("WIN",base-timedelta(minutes=1),base+timedelta(minutes=5),str(self.db))),5)
    def test_expired_lease_can_be_reclaimed(self):
        owner=acquire_lease("po3-m1","WIN",str(self.db),"a",ttl_seconds=-1)
        self.assertIsNotNone(owner)
        new=acquire_lease("po3-m1","WIN",str(self.db),"b",ttl_seconds=90)
        self.assertEqual(new,"b")
        release_lease("po3-m1","WIN","b",str(self.db))
    def test_outcome_horizons_and_future_exclusion(self):
        cut=datetime(2026,1,1,12,0,tzinfo=timezone.utc)
        bars=[{"timestamp_utc":cut+timedelta(minutes=i),"high":100+i,"low":100-i,"close":100+i} for i in range(1,61)]
        rows=calculate_outcomes(state_id=1,symbol="WIN",cutoff_at_utc=cut,start_price=100,bars=bars)
        self.assertEqual([x["horizon_code"] for x in rows],["5m","15m","30m","60m"])
        self.assertEqual(rows[0]["future_price"],104)
        self.assertEqual(rows[1]["future_high"],114)
        self.assertEqual(rows[2]["low_delta"],-29)
        self.assertEqual(rows[3]["status"],"DISPONIVEL")

if __name__=="__main__": unittest.main()
