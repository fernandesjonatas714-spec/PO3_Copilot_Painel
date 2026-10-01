import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from po3.collection.freshness import assess_freshness
from po3.collection.mt5_m1_collector import CollectorConfig, run_worker
from po3.collection.mt5_m1_collector import _record_freshness
from po3.collection.time_alignment import Mt5TimeAlignment, Mt5TimeAlignmentDetector
from po3.storage.market_repository import list_states

class FreshnessTests(unittest.TestCase):
    def test_current_feed(self):
        now=datetime(2026,10,1,12,0,tzinfo=timezone.utc)
        f=assess_freshness(last_closed_at_utc=now-timedelta(seconds=30),now_utc=now,market_active=True,max_lag_seconds=120)
        self.assertEqual(f.status,"ATUAL"); self.assertEqual(f.feed_lag_seconds,30)
    def test_stale_active_feed(self):
        now=datetime(2026,10,1,12,0,tzinfo=timezone.utc)
        f=assess_freshness(last_closed_at_utc=now-timedelta(minutes=10),now_utc=now,market_active=True,max_lag_seconds=120)
        self.assertEqual(f.status,"MT5_DATA_STALE")
    def test_closed_market_not_stale(self):
        now=datetime(2026,10,3,12,0,tzinfo=timezone.utc)
        f=assess_freshness(last_closed_at_utc=now-timedelta(hours=2),now_utc=now,market_active=None,max_lag_seconds=120)
        self.assertEqual(f.status,"SEM_NOVO_CANDLE_MERCADO_FECHADO")
    def test_closed_weekday_with_stopped_tick_not_really_stale(self):
        # 19:00 em Sao Paulo (22:00 UTC), fora da sessão configurada.
        now=datetime(2026,10,1,22,0,tzinfo=timezone.utc)
        alignment=Mt5TimeAlignmentDetector()
        alignment.last=Mt5TimeAlignment(now,None,None,10800,now-timedelta(minutes=20),
            "STALE","STALE","UNSTABLE_OFFSET",detail="tick parado")
        import os
        fd,db=tempfile.mkstemp(suffix=".sqlite"); os.close(fd)
        try: Path(db).unlink(missing_ok=True)
        except OSError: pass
        config=CollectorConfig("WIN",db)
        result=_record_freshness(config,[],alignment,now)
        self.assertEqual(result.status,"SEM_NOVO_CANDLE_MERCADO_FECHADO")
        self.assertFalse(result.market_active)
        try: Path(db).unlink(missing_ok=True)
        except OSError: pass

    def test_open_market_with_stopped_tick_remains_stale(self):
        now=datetime(2026,10,1,13,0,tzinfo=timezone.utc)  # 10:00 Sao Paulo
        f=assess_freshness(last_closed_at_utc=now-timedelta(minutes=10),now_utc=now,
                           market_active=True,max_lag_seconds=120,last_tick_at_utc=now-timedelta(minutes=10))
        self.assertEqual(f.status,"MT5_DATA_STALE")

    def test_weekend_is_closed_even_with_stopped_tick(self):
        now=datetime(2026,10,3,15,0,tzinfo=timezone.utc)
        f=assess_freshness(last_closed_at_utc=now-timedelta(hours=3),now_utc=now,
                           market_active=None,last_tick_at_utc=now-timedelta(hours=3))
        self.assertEqual(f.status,"SEM_NOVO_CANDLE_MERCADO_FECHADO")
    def test_stale_worker_does_not_create_state(self):
        import os
        fd,p=tempfile.mkstemp(suffix=".sqlite"); os.close(fd); db=Path(p)
        class Fake:
            TIMEFRAME_M1=1
            def copy_rates_from_pos(self,*args):
                old=datetime.now(timezone.utc)-timedelta(minutes=20)
                return [{"time":int(old.timestamp()),"open":1,"high":2,"low":0,"close":1}]
        run_worker(CollectorConfig("WIN",str(db),poll_seconds=1,max_feed_lag_seconds=1),Fake(),max_cycles=1,snapshot_provider=lambda c: (_ for _ in ()).throw(AssertionError("não deveria capturar")))
        self.assertEqual(list_states(str(db),"WIN"),[])
        try: db.unlink()
        except OSError: pass

if __name__=="__main__": unittest.main()
