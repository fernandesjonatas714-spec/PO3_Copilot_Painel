import unittest
from datetime import datetime, timezone, timedelta
from po3.outcome_engine import calculate_outcomes
class OutcomeBoundaryTests(unittest.TestCase):
    def test_target_1005_uses_open_times_1000_to_1004_only(self):
        cut=datetime(2026,1,1,10,0,tzinfo=timezone.utc)
        bars=[{"timestamp_utc":cut+timedelta(minutes=i),"high":100+i,"low":100-i,"close":100+i} for i in range(6)]
        rows=calculate_outcomes(state_id=1,symbol="WIN",cutoff_at_utc=cut,start_price=100,bars=bars,now_utc=cut+timedelta(minutes=6))
        five=next(x for x in rows if x["horizon_code"]=="5m")
        self.assertEqual(five["future_price"],104)
        self.assertEqual(five["future_high"],104)
        self.assertEqual(five["future_low"],96)
        self.assertEqual(five["high_delta"],4)
        self.assertEqual(five["low_delta"],-4)
        self.assertNotEqual(five["future_price"],105)
if __name__=="__main__": unittest.main()
