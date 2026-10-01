import unittest
from datetime import datetime, timedelta, timezone
from po3.collection.time_alignment import Mt5TimeAlignmentDetector, normalize_mt5_timestamp

class TimeAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.system = datetime(2026, 10, 1, 17, 50, tzinfo=timezone.utc)
    def test_offset_plus_10800_live(self):
        d=Mt5TimeAlignmentDetector()
        raw=int(self.system.timestamp())-10800
        d.observe(raw_tick_time=raw, raw_tick_time_msc=raw*1000, observed_at_system_utc=self.system)
        state=d.observe(raw_tick_time=raw+10, raw_tick_time_msc=(raw+10)*1000, observed_at_system_utc=self.system+timedelta(seconds=10))
        self.assertEqual(state.feed_liveness_status,"LIVE")
        self.assertEqual(state.clock_alignment_status,"OFFSET_DETECTED")
        self.assertAlmostEqual(state.detected_offset_seconds,10800,places=3)
        self.assertEqual(state.normalized_tick_at_utc,self.system+timedelta(seconds=10))
    def test_zero_offset_aligned(self):
        d=Mt5TimeAlignmentDetector()
        raw=int(self.system.timestamp())
        d.observe(raw_tick_time=raw,raw_tick_time_msc=raw*1000,observed_at_system_utc=self.system)
        state=d.observe(raw_tick_time=raw+10,raw_tick_time_msc=(raw+10)*1000,observed_at_system_utc=self.system+timedelta(seconds=10))
        self.assertEqual(state.clock_alignment_status,"ALIGNED")
        self.assertAlmostEqual(state.detected_offset_seconds,0)
    def test_stale_feed(self):
        d=Mt5TimeAlignmentDetector()
        d.observe(raw_tick_time=100,raw_tick_time_msc=100000,observed_at_system_utc=self.system)
        state=d.observe(raw_tick_time=100,raw_tick_time_msc=100000,observed_at_system_utc=self.system+timedelta(seconds=10))
        self.assertEqual(state.feed_liveness_status,"STALE")
        self.assertEqual(state.status,"STALE")
    def test_unstable_offset(self):
        d=Mt5TimeAlignmentDetector(offset_tolerance_seconds=2)
        base=int(self.system.timestamp())-10800
        d.observe(raw_tick_time=base,raw_tick_time_msc=base*1000,observed_at_system_utc=self.system)
        d.observe(raw_tick_time=base+10,raw_tick_time_msc=(base+10)*1000,observed_at_system_utc=self.system+timedelta(seconds=10))
        state=d.observe(raw_tick_time=base+11,raw_tick_time_msc=(base+11)*1000,observed_at_system_utc=self.system+timedelta(seconds=20))
        self.assertEqual(state.clock_alignment_status,"UNSTABLE_OFFSET")
    def test_m1_normalization(self):
        raw=1790866440
        canonical=normalize_mt5_timestamp(raw,10800)
        self.assertEqual(canonical,datetime(2026,10,1,17,54,tzinfo=timezone.utc))
    def test_restart_redetects(self):
        d=Mt5TimeAlignmentDetector()
        d.observe(raw_tick_time=100,raw_tick_time_msc=100000,observed_at_system_utc=self.system)
        d.observe(raw_tick_time=110,raw_tick_time_msc=110000,observed_at_system_utc=self.system+timedelta(seconds=10))
        fresh=Mt5TimeAlignmentDetector()
        self.assertFalse(fresh.usable)
        self.assertIsNone(fresh.last.detected_offset_seconds)
    def test_no_double_adjustment(self):
        canonical=datetime(2026,10,1,17,54,tzinfo=timezone.utc)
        self.assertEqual(normalize_mt5_timestamp(canonical,10800,already_normalized=True),canonical)

if __name__ == "__main__":
    unittest.main()

