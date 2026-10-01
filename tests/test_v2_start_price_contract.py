import json, os, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from po3.market_state_store import freeze_market_state
from po3.outcome_engine import calculate_outcomes
from po3.storage.market_repository import get_m1_bar, get_v2_m1_bar, insert_m1_bars, list_states

class StartPriceContractTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite"); os.close(fd)
        self.cut = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        self.symbol = "WIN"
    def tearDown(self):
        try: Path(self.path).unlink()
        except OSError: pass
    def _bar(self, minute, close, open_=None):
        t = self.cut + timedelta(minutes=minute)
        return {"symbol":self.symbol,"timestamp_utc":t,"open":open_ if open_ is not None else close,
                "high":close+1,"low":close-1,"close":close,"source":"test"}
    def _snapshot(self):
        rows=[{"time":self.cut+timedelta(minutes=i),"open":900+i,"high":901+i,"low":899+i,"close":900+i} for i in (-2,-1,0,4,5)]
        return SimpleNamespace(symbol=self.symbol,as_of=self.cut,last_price=999999,connected=True,
            source="test",bars={"M1":rows},levels={},zones={},macro={})
    def _freeze(self, start_price, status="DISPONIVEL"):
        return freeze_market_state(self._snapshot(),{},cutoff_at_utc=self.cut,db_path=self.path,
            symbol=self.symbol,start_price=start_price,start_bar_open_time=self.cut-timedelta(minutes=1),
            start_price_status=status)
    def test_exact_previous_close_is_start_price(self):
        sid=self._freeze(109)
        state=json.loads(list_states(self.path,self.symbol)[0]["state_json"])
        self.assertEqual(state["start_price"],109)
        self.assertEqual(state["start_bar_open_time"],"2026-01-01T09:59:00+00:00")
    def test_cutoff_open_is_not_start_price(self):
        sid=self._freeze(109)
        state=json.loads(list_states(self.path,self.symbol)[0]["state_json"])
        self.assertNotEqual(state["start_price"],900)
    def test_later_last_price_does_not_influence(self):
        self._freeze(109)
        state=json.loads(list_states(self.path,self.symbol)[0]["state_json"])
        self.assertNotEqual(state["start_price"],999999)
    def test_missing_previous_bar_has_no_fallback(self):
        self._freeze(None,"INDISPONIVEL")
        state=json.loads(list_states(self.path,self.symbol)[0]["state_json"])
        self.assertIsNone(state["start_price"])
        self.assertEqual(state["start_price_status"],"INDISPONIVEL")
        self.assertIsNone(get_m1_bar(self.symbol,self.cut-timedelta(minutes=1),self.path))
    def test_replay_preserves_exact_start_price(self):
        self._freeze(109)
        first=json.loads(list_states(self.path,self.symbol)[0]["state_json"])
        replay=json.loads(list_states(self.path,self.symbol)[0]["state_json"])
        self.assertEqual(first["start_price"],replay["start_price"])
        self.assertEqual(first["start_bar_open_time"],replay["start_bar_open_time"])
    def test_outcome_5m_uses_1000_to_1004_only(self):
        bars=[{"timestamp_utc":self.cut+timedelta(minutes=i),"high":100+i,"low":100-i,"close":100+i} for i in range(6)]
        row=next(x for x in calculate_outcomes(state_id=1,symbol=self.symbol,cutoff_at_utc=self.cut,
            start_price=109,bars=bars,now_utc=self.cut+timedelta(minutes=6)) if x["horizon_code"]=="5m")
        self.assertEqual((row["future_price"],row["future_high"],row["future_low"],row["candles_observed"]),(104,104,96,5))
    def test_bar_1005_is_excluded(self):
        bars=[{"timestamp_utc":self.cut+timedelta(minutes=i),"high":100+i,"low":100-i,"close":100+i} for i in range(6)]
        row=next(x for x in calculate_outcomes(state_id=1,symbol=self.symbol,cutoff_at_utc=self.cut,
            start_price=109,bars=bars,now_utc=self.cut+timedelta(minutes=6)) if x["horizon_code"]=="5m")
        self.assertNotEqual(row["future_price"],105)
    def test_gap_does_not_change_definition(self):
        self.assertEqual(self._bar(-1,109,open_=100)["close"],109)
        self.assertEqual(self._bar(0,900,open_=900)["open"],900)
        self._freeze(109)
        state=json.loads(list_states(self.path,self.symbol)[0]["state_json"])
        self.assertEqual(state["start_price"],109)

    def test_legacy_bar_never_satisfies_v2_start_price(self):
        insert_m1_bars([self._bar(-1, 109)], self.path)
        self.assertIsNone(get_v2_m1_bar(self.symbol, self.cut-timedelta(minutes=1), self.path))

    def test_canonical_bar_satisfies_v2_start_price(self):
        bar=self._bar(-1, 109)
        bar.update(source_timestamp_raw=int((self.cut-timedelta(minutes=1)).timestamp()), time_offset_seconds=0)
        insert_m1_bars([bar], self.path)
        found=get_v2_m1_bar(self.symbol, self.cut-timedelta(minutes=1), self.path)
        self.assertIsNotNone(found)
        self.assertEqual(found["close"],109)

    def test_older_bar_does_not_fallback_when_exact_start_bar_is_missing(self):
        old=self._bar(-61, 185)
        old.update(source_timestamp_raw=int((self.cut-timedelta(minutes=61)).timestamp()), time_offset_seconds=0)
        insert_m1_bars([old], self.path)
        self.assertIsNone(get_v2_m1_bar(self.symbol, self.cut-timedelta(minutes=1), self.path))

    def test_wrong_start_bar_is_rejected(self):
        with self.assertRaises(ValueError):
            freeze_market_state(self._snapshot(),{},cutoff_at_utc=self.cut,db_path=self.path,
                symbol=self.symbol,start_price=109,start_bar_open_time=self.cut-timedelta(minutes=2),
                start_price_status="DISPONIVEL")
if __name__ == "__main__":
    unittest.main()

