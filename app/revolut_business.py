"""Official Business API read adapter; live execution is deliberately unavailable."""
import os
from datetime import datetime, timezone
from uuid import UUID
import requests
from .financial_provider import FinancialProvider


class RevolutBusinessAdapter(FinancialProvider):
    def __init__(self, session=None):
        self.session=session or requests.Session()
        self.token=os.environ.get('REVOLUT_BUSINESS_ACCESS_TOKEN','')
        self.environment=os.environ.get('REVOLUT_BUSINESS_ENV','sandbox')
        if self.environment not in {'sandbox','production'}:raise ValueError('Invalid Revolut environment.')
        self.base=('https://sandbox-b2b.revolut.com' if self.environment=='sandbox' else 'https://b2b.revolut.com')+'/api/1.0'
        self.scopes=set(os.environ.get('REVOLUT_BUSINESS_SCOPES','READ').split(','))

    def _get(self,path,params=None):
        if not self.token or 'READ' not in self.scopes:raise ValueError('Revolut READ API authorization required.')
        try:
            response=self.session.get(self.base+path,headers={'Authorization':'Bearer '+self.token},params=params,timeout=(5,20),allow_redirects=False)
            if response.status_code!=200:raise ValueError('Revolut API verification failed (HTTP '+str(response.status_code)+').')
            return response.json()
        except requests.RequestException:raise ValueError('Revolut API unavailable; no execution attempted.') from None

    def getAccounts(self):
        rows=self._get('/accounts')
        if not isinstance(rows,list):raise ValueError('Invalid Revolut accounts response.')
        return [{k:x.get(k) for k in ('id','name','currency','balance','state','updated_at')} for x in rows]

    def getBalances(self):return self.getAccounts()
    def getTransactions(self,**params):return self._get('/transactions',params)
    def getExpenses(self,**params):return self._get('/expenses',params)
    def getCards(self):
        rows=self._get('/cards')
        if not isinstance(rows,list):raise ValueError('Invalid Revolut cards response.')
        # No PAN, CVV, expiry or sensitive-card-data scope.
        return [{k:x.get(k) for k in ('id','label','state','virtual','spending_limits')} for x in rows]
    def getFundingInstructions(self,account_id):
        account_id=str(UUID(str(account_id)))
        return self._get('/accounts/'+account_id+'/bank-details')
    def getPaymentStatus(self,transaction_id):return self._get('/transaction/'+str(UUID(str(transaction_id))))
    def createPaymentDraft(self,*args,**kwargs):raise ValueError('WRITE draft capability requires separate verified setup; not enabled.')
    def executePayment(self,*args,**kwargs):raise ValueError('PAY disabled. Explicit setup and final approval required.')
    def cancelPayment(self,*args,**kwargs):raise ValueError('PAY disabled; cancellation must be reconciled with provider.')
    def getCapabilities(self):return self.capabilities()
    def capabilities(self):
        return {**super().capabilities(),'provider':'Revolut Business','selection':'PREFERRED_PENDING_ELIGIBILITY','environment':self.environment,'status':'UNVERIFIED' if self.token else 'ACTION_REQUIRED','verified':False,'configured':bool(self.token),'scopes':['READ'],'write':False,'payment':False,'cards':False,'human_action':'COMPLETAR ACTIVACIÓN FINANCIERA ZAR','next_step':'Acceder con zaragente031@gmail.com, comprobar cuenta existente y forma jurídica: Revolut Business no admite autónomos en España; evaluar Wise si no hay sociedad elegible. Completar personalmente teléfono/KYC y términos. Después autorizar Business API READ con certificado y OAuth. No habilitar PAY ni datos sensibles de tarjetas.'}

    def verify(self):
        accounts=self.getAccounts()
        return {'status':'CONNECTED','verified':True,'provider':'Revolut Business','environment':self.environment,'accounts':accounts,'last_sync':datetime.now(timezone.utc).isoformat(),'payment':False,'write':False,'scopes':['READ']}


def sync(scope,adapter=None):
    """Read authentic bank balances separately; do not turn deposits into revenue."""
    from . import holdings
    adapter=adapter or RevolutBusinessAdapter()
    try:snapshot=adapter.verify()
    except ValueError:
        with holdings.transaction(scope):
            state=holdings.read(scope)
            if state.get('financial_provider_snapshot'):
                state['financial_provider_snapshot'].update(status='ERROR',verified=False,last_attempt=holdings._now())
                holdings.write(scope,state)
        raise
    with holdings.transaction(scope):
        state=holdings.read(scope);state['financial_provider_snapshot']=snapshot;holdings.write(scope,state)
    return snapshot
