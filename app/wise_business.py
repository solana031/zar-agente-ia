"""Wise read-only adapter. A web login never verifies API capabilities."""
import os
from datetime import datetime, timezone
import requests
from .financial_provider import FinancialProvider


class WiseBusinessAdapter(FinancialProvider):
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.token = os.environ.get('WISE_API_TOKEN', '')
        self.environment = os.environ.get('WISE_API_ENV', 'production')
        if self.environment not in {'production', 'sandbox'}:
            raise ValueError('Invalid Wise environment.')
        self.base = 'https://api.wise.com' if self.environment == 'production' else 'https://api.wise-sandbox.com'

    def _get(self, path, params=None):
        if not self.token:
            raise ValueError('ACTION_REQUIRED: Wise READ API token required.')
        try:
            response = self.session.get(self.base + path, params=params,
                headers={'Authorization': 'Bearer ' + self.token}, timeout=(5, 20), allow_redirects=False)
            if response.status_code != 200:
                raise ValueError('Wise READ API unavailable (HTTP ' + str(response.status_code) + '); no payment attempted.')
            return response.json()
        except requests.RequestException:
            raise ValueError('Wise READ API unavailable; credentials and response omitted.') from None

    @staticmethod
    def _id(value):
        value = str(value)
        if not value.isdecimal():
            raise ValueError('Invalid Wise identifier.')
        return value

    def getAccounts(self):
        rows = self._get('/v1/profiles')
        if not isinstance(rows, list):
            raise ValueError('Invalid Wise profiles response.')
        return [{'id': self._id(x['id']), 'type': x.get('type')} for x in rows if x.get('type') == 'business']

    def getBalances(self):
        rows = []
        for profile in self.getAccounts():
            balances = self._get('/v4/profiles/' + profile['id'] + '/balances', {'types': 'STANDARD'})
            if not isinstance(balances, list):
                raise ValueError('Invalid Wise balances response.')
            for b in balances:
                amount = b.get('amount') or {}
                rows.append({'id': self._id(b['id']), 'profile_id': profile['id'],
                    'currency': amount.get('currency'), 'balance': amount.get('value'), 'state': b.get('type')})
        return rows

    def getTransactions(self, profile_id, interval_start, interval_end):
        return self._get('/v1/transfers', {'profile': self._id(profile_id),
            'createdDateStart': interval_start, 'createdDateEnd': interval_end})

    def getFundingInstructions(self, account_id):
        # A balance ID is not a bank-details ID. Never guess an IBAN or order paid details.
        self._id(account_id)
        raise ValueError('ACTION_REQUIRED: consultar Get account details en Wise; no hay instrucciones bancarias verificadas por este adaptador READ. No ordenar datos de cuenta ni pagar activación automáticamente.')

    def getPaymentStatus(self, transaction_id):
        return self._get('/v1/transfers/' + self._id(transaction_id))

    def capabilities(self):
        return {**super().capabilities(), 'provider': 'Wise Business', 'environment': self.environment,
            'status': 'UNVERIFIED' if self.token else 'ACTION_REQUIRED', 'verified': False,
            'configured': bool(self.token), 'scopes': ['READ'], 'write': False, 'payment': False,
            'balance': False, 'deposit': False, 'transactions': False,
            'human_action': 'ACTIVAR WISE BUSINESS / API', 'url': 'https://wise.com/partner-integration/apps',
            'next_step': 'Reutilizar la cuenta empresarial ZAR existente. Autorizar token exclusivamente READ y guardarlo solo en servidor. Verificar profiles y balances por API; los extractos y financiación pueden estar restringidos para tokens personales en España. No habilitar PAY ni crear otra cuenta.'}

    def verify(self):
        profiles = self.getAccounts()
        if not profiles:
            raise ValueError('ACTION_REQUIRED: Wise API did not return a business profile.')
        accounts = self.getBalances()
        return {**self.capabilities(), 'status': 'CONNECTED', 'verified': True,
            'profiles': profiles, 'accounts': accounts, 'balance': True,
            'last_sync': datetime.now(timezone.utc).isoformat(),
            'next_step': 'READ profiles y balances verificados. Instrucciones de fondos y movimientos requieren pruebas separadas; PAY deshabilitado.'}

    def createPaymentDraft(self, *args, **kwargs):
        raise ValueError('Wise WRITE disabled; READ only.')

    def executePayment(self, *args, **kwargs):
        raise ValueError('Wise PAY disabled.')

    def cancelPayment(self, *args, **kwargs):
        raise ValueError('Wise PAY disabled; no cancellation submitted.')
