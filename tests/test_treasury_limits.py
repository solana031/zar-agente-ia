import unittest, tempfile, os
from unittest.mock import patch
from app import business_orchestration as control
class TreasuryLimitsTests(unittest.TestCase):
 def test_action_day_limits_and_no_execution(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'ZAR_DATA_DIR':tmp},clear=True):
   scope='fixture-only';control.mutate(scope,'mode',{'mode':'ACTIVE'});control.mutate(scope,'deposit',{'amount':'100','reference':'fixture-book-only'})
   control.mutate(scope,'budget',{'business':'sites','currency':'EUR','assigned':'25','max_action':'5','max_day':'10','max_month':'25'})
   def request(amount):
    row=control.mutate(scope,'prepare',{'business':'sites','item':'fixture only','provider':'fixture','price':amount,'tax':'0','currency':'EUR'});return row['approvals'][-1]
   denied=request('6')
   with self.assertRaises(ValueError):control.mutate(scope,'approve',{'id':denied['id'],'total':denied['total'],'confirmed':True})
   for i in range(2):
    a=request('4');control.mutate(scope,'approve',{'id':a['id'],'total':a['total'],'confirmed':True})
   a=request('4')
   with self.assertRaises(ValueError):control.mutate(scope,'approve',{'id':a['id'],'total':a['total'],'confirmed':True})
   state=control.view(scope);self.assertEqual(len(state['ledger']),1);self.assertEqual(state['wallet']['balances']['EUR']['expenses'],'0');self.assertTrue(all(a['execution_state']=='NO DISPONIBLE' for a in state['approvals']))
if __name__=='__main__':unittest.main()
