import os
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch
from app.wise_business import WiseBusinessAdapter
from app.financial_provider import selected_provider
from app.business_orchestration import reconcile_balances


class WiseReadTests(unittest.TestCase):
    def adapter(self, responses):
        session=Mock()
        session.get.side_effect=[Mock(status_code=code,json=Mock(return_value=data)) for code,data in responses]
        return WiseBusinessAdapter(session)

    @patch.dict(os.environ, {'WISE_API_TOKEN':'test-only'})
    def test_actual_capabilities_require_balance_request(self):
        profiles=[{'id':12,'type':'business','details':{'private':'not exposed'}}]
        balances=[{'id':45,'amount':{'value':0,'currency':'EUR'},'type':'STANDARD'}]
        a=self.adapter([(200,profiles),(200,profiles),(200,balances)])
        self.assertFalse(a.capabilities()['verified'])
        result=a.verify()
        self.assertTrue(result['balance']);self.assertFalse(result['payment'])
        self.assertEqual(result['accounts'][0]['balance'],0)
        self.assertNotIn('details',result['profiles'][0])
        self.assertFalse(a.session.get.call_args.kwargs['allow_redirects'])

    @patch.dict(os.environ, {'WISE_API_TOKEN':'test-only'})
    def test_partial_auth_does_not_claim_bank_connected(self):
        profiles=[{'id':12,'type':'business'}]
        a=self.adapter([(200,profiles),(200,profiles),(403,{})])
        with self.assertRaises(ValueError):a.verify()
        self.assertFalse(a.capabilities()['verified'])

    def test_never_execute_or_guess_funding(self):
        a=self.adapter([])
        for name in ('executePayment','createPaymentDraft','cancelPayment','createPayment','refund'):
            with self.assertRaises(ValueError):getattr(a,name)({})
        with self.assertRaises(ValueError):a.getFundingInstructions('45')
        a.session.get.assert_not_called()

    @patch.dict(os.environ, {'FINANCIAL_PROVIDER':'wise'})
    def test_neutral_selection(self):
        self.assertIsInstance(selected_provider(),WiseBusinessAdapter)

    def test_reconcile_does_not_mutate_or_mix_currencies(self):
        d={'financial_provider_snapshot':{'verified':True,'status':'CONNECTED','accounts':[
            {'currency':'EUR','balance':'25'},{'currency':'USD','balance':'10'}]},
            'ledger':[{'currency':'EUR','amount':20,'kind':'deposit','status':'collected'}]}
        before=deepcopy(d)
        # wallet ensures orchestrator defaults, so isolate its accounting contract.
        with patch('app.business_orchestration.wallet',return_value={'balances':{'EUR':{'manual_funding':'20'}}}):
            result=reconcile_balances(d)
        self.assertEqual(d,before)
        self.assertEqual(result['status'],'UNRECONCILED')
        self.assertEqual([x['delta'] for x in result['currencies']],['5','10'])

    def test_failed_snapshot_is_not_reconciled(self):
        self.assertEqual(reconcile_balances({'financial_provider_snapshot':{'verified':False}})['status'],'ACTION_REQUIRED')
