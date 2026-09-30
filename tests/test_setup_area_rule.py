import unittest
from test_setup_area import matches, invalid, newborn

class AreaRuleTests(unittest.TestCase):
    def test_four_combinations(self):
        for high in ('OB','FVG'):
            for low in ('OB','FVG'):
                for d in (-1,1):
                    self.assertTrue(matches((high,d,90,110,0,300),(low,d,95,105,300,480)))

    def test_rejects_early_opposite_or_outside(self):
        h=('OB',1,90,110,0,300)
        for l in [('FVG',1,95,105,240,420),('FVG',-1,95,105,300,480),('FVG',1,85,105,300,480)]:
            self.assertFalse(matches(h,l))

    def test_touch_does_not_invalidate(self):
        h=('OB',1,90,110,0,300)
        self.assertFalse(invalid(h,90))
        self.assertFalse(invalid(h,95))
        self.assertTrue(invalid(h,89))
        self.assertTrue(invalid(('OB',-1,90,110,0,300),111))

    def test_no_formation_across_missing_candle(self):
        bars=[dict(time=t,open=100,high=105,low=95,close=100) for t in [0,60,180]]
        self.assertEqual(newborn(bars,60),[])

if __name__=='__main__':unittest.main()
