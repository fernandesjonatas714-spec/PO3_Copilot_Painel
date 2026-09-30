import unittest
from statistical_audit import build, simulate, stats

def bar(t,o,h,l,c):
    return dict(time=t,open=o,high=h,low=l,close=c)

class AuditTests(unittest.TestCase):
    def test_ob_confirmation_is_impulse_close(self):
        bars=[bar(0,99,100,98,99),bar(60,99,100,98,99),bar(120,100,101,98,99),bar(180,99,110,99,109)]
        self.assertFalse(build(bars[:3],60))
        blocks=[z for z in build(bars,60) if z[0]=='OB']
        self.assertEqual(blocks[0][5],240)

    def test_tick_rounding_and_same_bar_conservative(self):
        z=('OB',1,90,100,0,300)
        bars=[bar(600,105,106,104,105),bar(660,105,150,80,110)]
        trades,_=simulate(bars,[(0,z,z,'OB+FVG')],5,1,2)
        self.assertEqual(trades[0]['stop'],85)
        self.assertEqual(trades[0]['target'],145)
        self.assertEqual(trades[0]['r'],-1)
        self.assertTrue(trades[0]['ambiguous'])
        self.assertLess(stats(trades,5)['total_r'],-1)

    def test_gap_exit_is_counted(self):
        z=('OB',1,90,100,0,300)
        bars=[bar(600,105,106,104,105),bar(660,105,110,100,107),bar(900,107,108,106,107)]
        trades,_=simulate(bars,[(0,z,z,'OB+FVG')],5,1,2)
        self.assertEqual(trades[0]['reason'],'fim_sessao_ou_lacuna')
        self.assertEqual(trades[0]['pnl_points'],2)

    def test_missing_entry_minute_rejects_trade(self):
        z=('OB',1,90,100,0,300)
        trades,skip=simulate([bar(600,105,106,104,105),bar(900,105,150,80,110)],[(0,z,z,'OB')],5,1,2)
        self.assertFalse(trades)
        self.assertEqual(skip['sem_proximo_minuto'],1)

if __name__=='__main__':unittest.main()
