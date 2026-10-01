import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from po3.storage.market_repository import insert_market_state, insert_m1_bars, get_outcomes
from po3.outcome_engine import process_pending_outcomes
class OutcomeTransitionTests(unittest.TestCase):
    def test_pending_data_then_available_without_duplicate(self):
        fd,p=tempfile.mkstemp(suffix=".sqlite"); os.close(fd); db=Path(p)
        cut=datetime(2026,1,1,10,0,tzinfo=timezone.utc)
        sid=insert_market_state({"preco_atual":100,"snapshot":{"cutoff_at_utc":cut.isoformat()}},str(db),cutoff_at_utc=cut,symbol="WIN")
        now=cut+timedelta(minutes=5)
        insert_m1_bars([{"symbol":"WIN","timestamp_utc":cut+timedelta(minutes=1),"open":100,"high":101,"low":99,"close":100.5}],str(db))
        process_pending_outcomes(str(db),symbol="WIN",now_utc=now)
        first=next(x for x in get_outcomes(str(db),sid) if x["horizon_code"]=="5m")
        self.assertIn(first["status"],{"PENDENTE_DADOS","MERCADO_FECHADO"})
        insert_m1_bars([{"symbol":"WIN","timestamp_utc":cut+timedelta(minutes=4),"open":100,"high":104,"low":96,"close":103}],str(db))
        process_pending_outcomes(str(db),symbol="WIN",now_utc=cut+timedelta(minutes=8))
        rows=get_outcomes(str(db),sid); five=next(x for x in rows if x["horizon_code"]=="5m")
        self.assertEqual(five["status"],"DISPONIVEL")
        self.assertEqual(len([x for x in rows if x["horizon_code"]=="5m"]),1)
        try:db.unlink()
        except OSError:pass
if __name__=="__main__":unittest.main()
