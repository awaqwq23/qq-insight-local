import unittest
import test_ai
from local_assistant.service import AssistantService
from local_assistant.errors import CoreError
from local_assistant.ai_schema import BUDGET_LIMITS

class BudgetRegressionTest(unittest.TestCase):
    setUp=test_ai.AITest.setUp
    add_message=test_ai.AITest.add_message
    prepare=test_ai.AITest.prepare

    def test_maximum_limits_persist_across_restart(self):
        maximum={key:value['max'] for key,value in BUDGET_LIMITS.items()}
        self.ai.save_budget(maximum)
        restored=AssistantService(self.root/'app').ai.budget()
        for key,value in maximum.items():self.assertEqual(restored[key],value)
        self.assertEqual(restored['limits'],BUDGET_LIMITS)

    def test_invalid_save_identifies_field_and_does_not_partially_save(self):
        before=self.ai.budget()
        with self.assertRaises(CoreError) as raised:
            self.ai.save_budget({'per_run_tokens':10000000,'daily_tokens':100000001})
        self.assertEqual(raised.exception.data['field'],'daily_tokens')
        self.assertIn('未保存',str(raised.exception));self.assertIn('每日',str(raised.exception))
        self.assertEqual(self.ai.budget()['per_run_tokens'],before['per_run_tokens'])
        self.assertEqual(self.ai.budget()['daily_tokens'],before['daily_tokens'])

    def test_raise_budget_allows_same_job_without_erasing_usage(self):
        for _ in range(4):
            entry=self.ai.ledger.reserve_call(test_ai.MODEL,'test_vision',70000,0)
            self.ai.ledger.settle_call(entry['attempt'],{'input_tokens':70000,'output_tokens':0})
        prepared=self.prepare()
        with self.assertRaises(CoreError) as raised:
            self.ai.ledger.reserve_call(test_ai.MODEL,'vision',25000,4096,job_id=prepared['job_id'])
        blocked=raised.exception.data['blocked']
        self.assertEqual([item['field'] for item in blocked],['daily_tokens'])
        self.assertEqual(blocked[0]['remaining'],20000);self.assertEqual(blocked[0]['required'],29096)
        self.assertEqual(self.ai.budget()['daily_used'],280000)
        self.ai.fail(prepared['job_id'],message=str(raised.exception))
        self.ai.save_budget({key:BUDGET_LIMITS[key]['max'] for key in ('per_run_tokens','daily_tokens','monthly_tokens')})
        self.ai.resume(prepared['job_id'],'a','group-a',test_ai.MODEL)
        request=self.ai.next_chunk(prepared['job_id'])
        self.assertFalse(request['done']);self.assertGreater(self.ai.budget()['daily_used'],280000)

    def test_error_reports_each_exhausted_limit(self):
        self.ai.save_budget({'per_run_tokens':1000,'daily_tokens':1000,'monthly_tokens':1000})
        with self.assertRaises(CoreError) as raised:self.ai.ledger.reserve_call(test_ai.MODEL,'vision',1200,512)
        self.assertEqual(len(raised.exception.data['blocked']),3)
        self.assertIn('本次分析',str(raised.exception));self.assertIn('今日',str(raised.exception));self.assertIn('本月',str(raised.exception))
        self.assertEqual(self.ai.ledger.list()['items'],[])

    def test_no_image_chunk_has_no_image_allowance(self):
        first=self.prepare();request=self.ai.next_chunk(first['job_id']);original=self.ai.budget()['daily_used']
        self.ai.fail(first['job_id'],attempt=request['attempt'],known_not_sent=True)
        self.ai.save_group('group-a','a',{'images':True})
        second=self.prepare();request=self.ai.next_chunk(second['job_id'])
        self.assertEqual(request['images'],[])
        self.assertLessEqual(self.ai.budget()['daily_used'],original+100)

if __name__=='__main__':unittest.main()
