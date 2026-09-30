from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from po3.book_rules import DetectionConfig, detect_book_po3
from po3.demo_data import build_demo_snapshot
from po3.engine import ChecklistState, calculate_rr, status_from_checklist
from po3.levels import build_daily_zones
from po3.models import MarketSnapshot


def bar(time: datetime, open_price: float, high: float, low: float, close: float) -> dict:
    return {
        "time": time,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "tick_volume": 100,
    }


class CoreTests(unittest.TestCase):
    def test_demo_has_required_timeframes_and_levels(self) -> None:
        snapshot = build_demo_snapshot()
        self.assertEqual(set(snapshot.bars), {"D1", "M15", "M5", "M1"})
        self.assertEqual(len(snapshot.levels["M15"]), 6)
        self.assertEqual(len(snapshot.levels["M5"]), 5)
        self.assertEqual(snapshot.levels["M1"], [])
        self.assertTrue(snapshot.zones["M15"])

    def test_daily_zones_keep_only_active_fvg_and_order_block(self) -> None:
        start = datetime(2026, 9, 1)
        daily = [
            bar(start, 100, 102, 98, 99),
            bar(start + timedelta(days=1), 99, 111, 98, 110),
            bar(start + timedelta(days=2), 110, 115, 109, 114),
            bar(start + timedelta(days=3), 116, 120, 116, 119),
            bar(start + timedelta(days=4), 119, 121, 118, 120),
            bar(start + timedelta(days=5), 120, 122, 119, 121),
        ]
        zones = build_daily_zones(daily)
        self.assertTrue(any(zone.kind == "OB" and zone.direction == "COMPRA" for zone in zones))
        self.assertTrue(any(zone.kind == "FVG" and zone.direction == "COMPRA" for zone in zones))

    def test_status_requires_every_check(self) -> None:
        complete = ChecklistState(True, True, True, True, True, True)
        partial = ChecklistState(True, True, False, False, False, False)
        empty = ChecklistState(False, False, False, False, False, False)
        self.assertEqual(status_from_checklist(complete)[0], "VERDE")
        self.assertEqual(status_from_checklist(partial)[0], "AMARELO")
        self.assertEqual(status_from_checklist(empty)[0], "VERMELHO")

    def test_rr_calculation(self) -> None:
        self.assertEqual(calculate_rr("compra", 100.0, 90.0, 120.0), 2.0)
        self.assertEqual(calculate_rr("venda", 100.0, 110.0, 80.0), 2.0)
        self.assertIsNone(calculate_rr("compra", 100.0, 110.0, 120.0))

    def test_book_sequence_detects_bullish_setup(self) -> None:
        start = datetime(2026, 9, 3, 9, 0)
        m15 = [
            bar(start + timedelta(minutes=15 * index), 103, 105 + (index % 2), 100 + (index % 2), 103)
            for index in range(4)
        ]
        m15.extend(
            [
                bar(start + timedelta(minutes=60), 103, 106, 101, 104),
                bar(start + timedelta(minutes=75), 104, 107, 102, 105),
            ]
        )

        m5 = [
            bar(start + timedelta(minutes=5 * index), 102, 105 + (index % 3), 100, 103)
            for index in range(12)
        ]
        m5.extend(
            [
                bar(start + timedelta(minutes=65), 102, 104, 98, 101),
                bar(start + timedelta(minutes=70), 101, 110, 101, 109),
                bar(start + timedelta(minutes=75), 109, 111, 108, 110),
                bar(start + timedelta(minutes=80), 110, 112, 109, 111),
            ]
        )

        m1 = [
            bar(start + timedelta(minutes=65), 102, 103, 101.5, 102.5),
            bar(start + timedelta(minutes=66), 102.5, 103.5, 102, 103),
            bar(start + timedelta(minutes=67), 103, 104, 102.5, 103.5),
            bar(start + timedelta(minutes=68), 103.5, 105.5, 103, 105),
            bar(start + timedelta(minutes=69), 106, 106.5, 105.5, 105.5),
            bar(start + timedelta(minutes=70), 105, 107, 104, 106),
            bar(start + timedelta(minutes=71), 106, 109, 106, 108),
            bar(start + timedelta(minutes=72), 108, 111, 108, 110),
            bar(start + timedelta(minutes=73), 107.5, 109.5, 107.5, 109),
            bar(start + timedelta(minutes=74), 109, 110, 108, 109.5),
        ]
        snapshot = MarketSnapshot(
            symbol="TESTE",
            as_of=start + timedelta(minutes=90),
            last_price=109.5,
            connected=False,
            source="teste",
            bars={"M15": m15, "M5": m5, "M1": m1},
        )
        detection = detect_book_po3(
            snapshot,
            DetectionConfig(accumulation_max_atr=5.0, displacement_body_factor=1.2),
        )
        self.assertEqual(detection.stage, 5)
        self.assertEqual(detection.direction, "COMPRA")
        self.assertIsNotNone(detection.fvg)
        self.assertIsNotNone(detection.order_block)
        self.assertEqual(detection.order_block.validation, "EXCELENTE")
        self.assertIsNotNone(detection.retest_time)

    def test_book_sequence_detects_bearish_setup(self) -> None:
        start = datetime(2026, 9, 3, 9, 0)
        m15 = [
            bar(start + timedelta(minutes=15 * index), 103, 105 + (index % 2), 100 + (index % 2), 103)
            for index in range(4)
        ]
        m15.extend(
            [
                bar(start + timedelta(minutes=60), 103, 106, 101, 104),
                bar(start + timedelta(minutes=75), 104, 107, 102, 105),
            ]
        )
        m5 = [
            bar(start + timedelta(minutes=5 * index), 103, 106, 100 + (index % 2), 102)
            for index in range(12)
        ]
        m5.extend(
            [
                bar(start + timedelta(minutes=65), 104, 108, 103, 105),
                bar(start + timedelta(minutes=70), 105, 105, 97, 98),
                bar(start + timedelta(minutes=75), 98, 100, 96, 97),
                bar(start + timedelta(minutes=80), 97, 99, 95, 96),
            ]
        )
        m1 = [
            bar(start + timedelta(minutes=65), 103, 103.5, 102.5, 103.25),
            bar(start + timedelta(minutes=66), 103.25, 103.5, 102.5, 103),
            bar(start + timedelta(minutes=67), 103, 103.25, 102, 102.5),
            bar(start + timedelta(minutes=68), 102.5, 102.75, 100.5, 101),
            bar(start + timedelta(minutes=69), 100, 101, 100, 100.5),
            bar(start + timedelta(minutes=70), 103, 104, 101, 102),
            bar(start + timedelta(minutes=71), 102, 102, 98, 99),
            bar(start + timedelta(minutes=72), 99, 99, 96, 97),
            bar(start + timedelta(minutes=73), 100.5, 100.5, 98, 98.5),
            bar(start + timedelta(minutes=74), 98.5, 99, 97, 98),
        ]
        snapshot = MarketSnapshot(
            symbol="TESTE",
            as_of=start + timedelta(minutes=90),
            last_price=98.0,
            connected=False,
            source="teste",
            bars={"M15": m15, "M5": m5, "M1": m1},
        )
        detection = detect_book_po3(
            snapshot,
            DetectionConfig(accumulation_max_atr=5.0, displacement_body_factor=1.2),
        )
        self.assertEqual(detection.stage, 5)
        self.assertEqual(detection.direction, "VENDA")
        self.assertIsNotNone(detection.fvg)
        self.assertIsNotNone(detection.order_block)
        self.assertEqual(detection.order_block.validation, "EXCELENTE")
        self.assertIsNotNone(detection.retest_time)


if __name__ == "__main__":
    unittest.main()
