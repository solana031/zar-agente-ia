"""Financial execution contract. Stripe collection is not treasury money transfer."""
class FinancialProvider:
    def getAccounts(self):return []
    def getBalances(self):return self.balance()
    def getTransactions(self):return []
    def getExpenses(self):return []
    def getCards(self):return []
    def createPaymentDraft(self,*args,**kwargs):raise ValueError('Verified WRITE capability required.')
    def executePayment(self,*args,**kwargs):return self.createPayment(*args,**kwargs)
    def getPaymentStatus(self,*args,**kwargs):return self.paymentStatus(*args,**kwargs)
    def cancelPayment(self,*args,**kwargs):raise ValueError('Verified cancellation capability required.')
    def getFundingInstructions(self,*args,**kwargs):return self.depositInstructions()
    def getCapabilities(self):return self.capabilities()
    def capabilities(self):
        return {'status':'ACTION_REQUIRED','balance':False,'deposit':False,'payment':False,'refund':False,'account':'zaragente031@gmail.com','human_action':'ACTIVAR PROVEEDOR FINANCIERO ZAR','next_step':'Seleccionar proveedor de tesorería y completar su alta oficial, identidad/KYC, banco, términos y autorización de pagos. Stripe Checkout existente sirve para cobros; no habilita transferencias.'}
    def balance(self):return {'amount':None,'status':'NOT_CONFIGURED'}
    def depositInstructions(self):return self.capabilities()
    def createPayment(self,*args,**kwargs):raise ValueError('Financial execution disabled: verified provider and separate confirmation required.')
    def paymentStatus(self,*args,**kwargs):return {'status':'NOT_CONFIGURED'}
    def refund(self,*args,**kwargs):raise ValueError('Financial refunds disabled.')

def execute_reserved(scope, approval_id, provider, *, confirmed=False):
    """Internal adapter boundary. No HTTP endpoint or production payment provider."""
    from . import holdings, jev_decision
    from decimal import Decimal
    caps=provider.capabilities()
    if confirmed is not True or caps.get('payment') is not True or caps.get('verified') is not True:
        raise ValueError('Verified execution capability and final confirmation required.')
    gate=jev_decision.evaluate(scope,{'action':'PAYMENT','agent':'Treasury','task_id':approval_id})
    if gate['decision']=='DENY':raise ValueError('JEV denied execution.')
    with holdings.transaction(scope):
        d=holdings.read(scope);o=d['orchestration'];p=next(x for x in o['approvals'] if x['id']==approval_id)
        if d.get('global_stop') or o['mode'] not in {'ACTIVE','SUPERVISED'} or p['state']!='APPROVED' or p.get('execution_state')!='NO DISPONIBLE':raise ValueError('Reservation/mode not executable.')
        budget=d.get('treasury_budgets',{}).get(p.get('business'))
        if not budget or budget['currency']!=p['currency'] or Decimal(p['total'])>Decimal(budget['max_action']):raise ValueError('Current budget required.')
        approved=[x for x in o['approvals'] if x.get('business')==p['business'] and x['state'] in {'APPROVED','EXECUTED'}]
        from .business_orchestration import wallet
        if Decimal(wallet(d)['balances'].get(p['currency'],{}).get('available','0'))<0:raise ValueError('Book funds no longer sufficient.')
        for key,prefix in [('assigned',''),('max_day',holdings._now()[:10]),('max_month',holdings._now()[:7])]:
            if sum((Decimal(x['total']) for x in approved if str(x.get('updated_at') or x['created_at']).startswith(prefix)),Decimal(0))>Decimal(budget[key]):raise ValueError('Current limits exceeded.')
        p.update(execution_state='REQUESTED',updated_at=holdings._now());holdings.write(scope,d)
    try:result=provider.createPayment(dict(p),idempotency_key=approval_id)
    except Exception:result={'status':'UNKNOWN'}
    with holdings.transaction(scope):
        d=holdings.read(scope);p=next(x for x in d['orchestration']['approvals'] if x['id']==approval_id)
        if result.get('status')=='FAILED' and result.get('definitive') is True:
            p.update(state='FAILED',execution_state='FAILED',updated_at=holdings._now())
        else:
            # Even a claimed success waits for authenticated receipt reconciliation.
            p.update(execution_state='REVIEW_REQUIRED',updated_at=holdings._now())
        holdings.write(scope,d)
    return dict(p)

def reconcile_payment(scope, approval_id, provider):
    """Read-only verified receipt reconciliation; never submit or retry payment."""
    from . import holdings
    from .financial_events import ingest
    from decimal import Decimal
    caps=provider.capabilities()
    if caps.get('verified') is not True or caps.get('payment') is not True:raise ValueError('Verified financial adapter required.')
    receipt=provider.paymentStatus(approval_id)
    with holdings.transaction(scope):
        d=holdings.read(scope);p=next(x for x in d['orchestration']['approvals'] if x['id']==approval_id)
        if p['state']=='EXECUTED':return dict(p)
        if p['state']!='APPROVED' or p.get('execution_state') not in {'REQUESTED','REVIEW_REQUIRED'}:raise ValueError('No submitted reservation to reconcile.')
        if receipt.get('verified') is not True or receipt.get('status')!='PAID' or Decimal(str(receipt.get('amount')))!=Decimal(p['total']) or receipt.get('currency')!=p['currency']:raise ValueError('Authenticated, matching paid receipt required.')
        business={'clipper':'media','reselling':'commerce','agency':'web_agency','infrastructure':'zar','marketing':'zar'}.get(p['business'],p['business'])
        ingest(scope,'cost',{'provider':receipt['provider'],'business':business,'amount':receipt['amount'],'currency':receipt['currency'],'timestamp':receipt['timestamp'],'external_id':receipt['external_id'],'source':'FINANCIAL_PROVIDER_RECEIPT','task_id':approval_id},provider_verified=True)
        d=holdings.read(scope);p=next(x for x in d['orchestration']['approvals'] if x['id']==approval_id)
        p.update(state='EXECUTED',execution_state='CHARGED',updated_at=holdings._now());holdings.write(scope,d)
        return dict(p)
