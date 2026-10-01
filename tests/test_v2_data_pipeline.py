import tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from po3.storage.migrations import migrate
from po3.storage.market_repository import insert_m1_bars, get_m1_range, acquire_lease, release_lease, insert_market_state, upsert_outcome, get_outcomes
from po3.collection.mt5_m1_collector import closed_m1_bars
from po3.outcome_engine import calculate_outcomes
from po3.evaluation_engine import direction_match, summarize
from po3.replay_engine import replay

class FakeMT5:
    TIMEFRAME_M1=1
    def __init__(self, rows): self.rows=rows
    def copy_rates_from_pos(self,*args): return self.rows

class V2PipelineTests(unittest.TestCase):
    def setUp(self):
        fd,path=tempfile.mkstemp(suffix='.sqlite'); import os; os.close(fd); self.path=Path(path)
    def tearDown(self):
        try:self.path.unlink()
        except OSError:pass
    def test_migration_idempotent_and_unique_bars(self):
        self.assertEqual(migrate(self.path),'2.0.0'); self.assertEqual(migrate(self.path),'2.0.0')
        t=datetime(2026,1,1,12,0,tzinfo=timezone.utc); b={'symbol':'WIN','timestamp_utc':t,'open':1,'high':2,'low':0,'close':1.5}
        self.assertEqual(insert_m1_bars([b,b],self.path),1); self.assertEqual(len(get_m1_range('WIN',t-timedelta(minutes=1),t,self.path)),1)
    def test_closed_candle_excludes_forming(self):
        now=datetime(2026,1,1,12,2,30,tzinfo=timezone.utc)
        rows=[{'time':int((now-timedelta(minutes=2)).timestamp()),'open':1,'high':2,'low':0,'close':1.5}, {'time':int((now).timestamp()),'open':2,'high':3,'low':1,'close':2.5}]
        out=closed_m1_bars(FakeMT5(rows),'WIN',now); self.assertEqual(len(out),1)
    def test_lease_and_outcomes_are_idempotent(self):
        owner=acquire_lease('c','WIN',self.path,'a'); self.assertIsNotNone(owner); self.assertIsNone(acquire_lease('c','WIN',self.path,'b')); release_lease('c','WIN',owner,self.path)
        cut=datetime(2026,1,1,12,0,tzinfo=timezone.utc); state=insert_market_state({'preco_atual':100},self.path,cutoff_at_utc=cut,symbol='WIN')
        bars=[{'timestamp_utc':cut+timedelta(minutes=i),'high':100+i,'low':100-i,'close':100+i} for i in range(1,7)]
        outs=calculate_outcomes(state_id=state,symbol='WIN',cutoff_at_utc=cut,start_price=100,bars=bars); self.assertEqual(len(outs),4)
        upsert_outcome(outs[0],self.path); upsert_outcome(outs[0],self.path); self.assertEqual(len(get_outcomes(self.path,state)),1)
    def test_replay_removes_future_payload(self):
        seen=[]
        def runner(p): seen.append(p); return {'ok':True}
        replay([{'id':1,'future_bars':[1],'outcomes':[2],'cutoff_at_utc':'x'}],runner)
        self.assertNotIn('future_bars',seen[0]); self.assertNotIn('outcomes',seen[0])
    def test_metrics(self):
        self.assertTrue(direction_match('comprador',1)); self.assertFalse(direction_match('vendedor',1)); self.assertEqual(summarize([{'acerto':True},{'acerto':False}])['taxa_acerto'],.5)

if __name__=='__main__': unittest.main()
