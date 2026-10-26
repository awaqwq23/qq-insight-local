from datetime import datetime
import unittest
import test_ai as fixtures
from local_assistant.ai_accounting import calculate,price_at
from local_assistant.errors import CoreError

DS={'basis':'official','unit':'token','currency':'CNY','input_price':9,'output_price':27,'cached_input_price':0.3,'time_schedule':'deepseek_beijing','off_peak':{'input_price':4.5,'output_price':13.5,'cached_input_price':0.15}}
TIER={'basis':'official','unit':'token','currency':'USD','input_price':4,'output_price':20,'cached_input_price':0.4,'cache_write_price':5,'long_context':{'threshold':272000,'input_price':8,'output_price':30,'cached_input_price':0.8,'cache_write_price':10}}

class OfficialPricingTest(unittest.TestCase):
    setUp=fixtures.AITest.setUp
    add_message=fixtures.AITest.add_message

    def test_beijing_windows_holidays_and_start_frozen(self):
        for stamp,expected in [('2026-10-13T08:59:59+08:00',4.5),('2026-10-13T09:00:00+08:00',9),('2026-10-13T12:00:00+08:00',4.5),('2026-10-13T14:00:00+08:00',9),('2026-10-13T18:00:00+08:00',4.5),('2026-10-17T10:00:00+08:00',4.5),('2026-10-01T10:00:00+08:00',4.5),('2026-10-13T01:00:00+00:00',9)]:
            self.assertEqual(price_at(DS,datetime.fromisoformat(stamp))['input_price'],expected)
        entry=self.ai.ledger.reserve_call({**fixtures.MODEL,'pricing':DS},'test_capacity',1000,1000)
        self.assertAlmostEqual(entry['estimated_cost'],0.036)
        self.ai.ledger.settle_call(entry['attempt'],{'input_tokens':1000,'output_tokens':1000,'cached_tokens':500,'request_started_at':'2026-10-13T18:00:00+08:00'})
        row=self.ai.ledger.list()['items'][0];self.assertEqual(row['pricing']['time_band'],'闲时');self.assertAlmostEqual(row['cost'],0.015825)

    def test_whole_request_tier_boundary_and_reservation(self):
        self.ai.save_budget({'per_run_tokens':5000000,'daily_tokens':10000000})
        stamp=datetime.fromisoformat('2026-10-13T00:00:00+08:00')
        self.assertEqual(price_at(TIER,stamp,272000)['input_price'],4)
        high=price_at(TIER,stamp,272001);self.assertEqual(high['input_price'],8)
        self.assertEqual(price_at(high,stamp,1000)['input_price'],4)
        entry=self.ai.ledger.reserve_call({**fixtures.MODEL,'pricing':TIER},'test_capacity',300000,1000)
        self.assertAlmostEqual(entry['estimated_cost'],2.43)
        self.ai.ledger.settle_call(entry['attempt'],{'input_tokens':1000,'output_tokens':1000})
        self.assertAlmostEqual(self.ai.ledger.list()['items'][0]['cost'],0.024)

    def test_read_write_cache_no_double_count_and_unknown_usage(self):
        price={**TIER,'cache_write_1h_price':8}
        self.assertAlmostEqual(calculate(price,1000,100,200,cache_write=100,cache_write_1h=100),0.00578)
        self.assertIsNone(calculate(price,1000,100,800,cache_write=300))
        self.assertIsNone(calculate(price,None,None))

    def test_reprice_only_unpriced_history_idempotent_and_preserve_tokens(self):
        a=self.ai.ledger.reserve_call(fixtures.MODEL,'test_capacity',1000,100)
        self.ai.ledger.settle_call(a['attempt'],{'input_tokens':1000,'output_tokens':100})
        b=self.ai.ledger.reserve_call(fixtures.MODEL,'test_capacity',1000,100)
        self.ai.ledger.settle_call(b['attempt'])
        model=fixtures.MODEL['model'];self.assertEqual(self.ai.ledger.reprice_unknown({model:TIER})['updated'],2)
        rows={row['attempt']:row for row in self.ai.ledger.list()['items']}
        self.assertEqual(rows[a['attempt']]['input_tokens'],1000);self.assertAlmostEqual(rows[a['attempt']]['cost'],0.006)
        self.assertIsNone(rows[b['attempt']]['cost']);self.assertIsNone(rows[b['attempt']]['input_tokens'])
        self.assertTrue(rows[a['attempt']]['pricing']['reestimated_at']);self.assertEqual(self.ai.ledger.reprice_unknown({model:TIER})['updated'],0)
        with self.assertRaises(CoreError):self.ai.ledger.reprice_unknown([])
        with self.assertRaises(CoreError):self.ai.ledger.reprice_unknown({'bad':'not-a-price'})
