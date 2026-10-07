"""Atomic, explicit Wallet budget reservations for Paper; never bank transfers."""
from copy import deepcopy
from decimal import Decimal
import re
from . import holdings


def ensure(d):
    return d.setdefault('trading_capital',{'enabled':False,'transactions':[]})


def assigned(d,currency='USD'):
    total=Decimal(0)
    for row in ensure(d)['transactions']:
        if row['status']=='CONFIRMED' and row['currency']==currency:
            if row['action']=='assign':total+=Decimal(row['amount'])
            elif row['action']=='return':total-=Decimal(row['amount'])
    if total<0:raise ValueError('Ledger Trading inconsistente; operar bloqueado.')
    return total


def view(scope):
    from .business_orchestration import wallet
    d=holdings.read(scope);capital=ensure(d)
    book=wallet(d)['balances'].get('USD',{})
    # Business profits are never automatically eligible for Paper allocation.
    manual=max(Decimal(0),Decimal(book.get('manual_funding','0'))-Decimal(book.get('expenses','0'))-
               Decimal(book.get('committed','0'))-Decimal(book.get('pending_payments','0'))-assigned(d))
    available=max(Decimal(0),min(manual,Decimal(book.get('available','0'))))
    return {'currency':'USD','enabled':capital['enabled'],'assigned':str(assigned(d)),
            'wallet_available':str(available),'wallet_total_available':book.get('available','0'),
            'transactions':deepcopy(capital['transactions'][-100:][::-1]),
            'note':'Reserva contable explícita de aportaciones manuales USD. Paper usa saldo virtual del broker; no se envía dinero ni se abonan ganancias Paper a Wallet.'}


def move(scope,data,broker_snapshot):
    from .business_orchestration import money
    action=data.get('action');currency=data.get('currency','USD')
    if action not in {'assign','return','reverse'} or currency!='USD':raise ValueError('Asignar/devolver/revertir presupuesto Paper en USD; sin conversión de divisas.')
    if data.get('confirmed') is not True:raise ValueError('Confirma el movimiento contable.')
    tid=str(data.get('transaction_id') or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',tid):raise ValueError('transaction_id único requerido.')
    amount=money(data.get('amount'));reason=str(data.get('reason') or '').strip()[:500]
    if not reason:raise ValueError('Motivo requerido.')
    signature={'action':action,'currency':currency,'amount':str(amount),'reason':reason,'reverses':data.get('reverses')}
    with holdings.transaction(scope):
        d=holdings.read(scope);capital=ensure(d)
        old=next((r for r in capital['transactions'] if r['transaction_id']==tid),None)
        if old:
            if old['request']!=signature:raise ValueError('transaction_id reutilizado con otros datos.')
            return deepcopy(old)
        if len(capital['transactions'])>=10000:raise ValueError('Límite del ledger alcanzado; conservar histórico.')
        before=view(scope);total=assigned(d)
        row={'transaction_id':tid,'timestamp':holdings._now(),'user':scope,'action':action,'currency':currency,
             'balance_before':{'wallet':before['wallet_total_available'],'trading':str(total)},'amount':str(amount),
             'balance_after':None,'source':'WALLET' if action=='assign' else 'AUTOMATON',
             'destination':'AUTOMATON' if action=='assign' else 'WALLET','reason':reason,'status':'PENDING',
             'request':signature,'events':[{'status':'PENDING','timestamp':holdings._now()}],'paper_budget_only':True}
        capital['transactions'].append(row);holdings.write(scope,d)
        try:
            account,positions,orders=broker_snapshot()
            if account.get('currency')!='USD' or account.get('status')!='ACTIVE':raise ValueError('Cuenta Paper USD activa requerida.')
            original=None
            if action=='assign':
                if amount>Decimal(before['wallet_available']):raise ValueError('Aportación manual disponible insuficiente; ingresos empresariales excluidos.')
                if total+amount>Decimal(str(account.get('equity') or 0)):raise ValueError('Presupuesto supera equity Paper disponible.')
            else:
                if positions or orders:raise ValueError('Devolución bloqueada mientras existan posiciones u órdenes Paper; cierra/cancela y reconcilia primero.')
                if amount>total:raise ValueError('Capital asignado insuficiente.')
                if action=='reverse':
                    original=next((r for r in capital['transactions'] if r['transaction_id']==data.get('reverses')),None)
                    if not original or original['action']!='assign' or original['status']!='CONFIRMED' or Decimal(original['amount'])!=amount:
                        raise ValueError('Reversión exige asignación confirmada e importe completo.')
            if original:
                original['status']='REVERSED';original['reversed_by']=tid
                original['events'].append({'status':'REVERSED','timestamp':holdings._now()})
            row['status']='CONFIRMED';row['events'].append({'status':'CONFIRMED','timestamp':holdings._now()})
            capital['enabled']=True
            holdings.write(scope,d)
            after=view(scope)
            row['balance_after']={'wallet':after['wallet_total_available'],'trading':after['assigned']}
        except Exception:
            row['status']='FAILED';row['balance_after']=row['balance_before']
            row['events'].append({'status':'FAILED','timestamp':holdings._now()})
            holdings.write(scope,d)
            raise
        holdings.write(scope,d)
        return deepcopy(row)


def check_order(d,body,positions,orders,price):
    """Apply an opted-in budget only to exposure increases. Exits keep fast-path."""
    if not ensure(d)['enabled']:return
    symbol=str(body.get('symbol'));side=str(body.get('side'));qty=Decimal(str(body.get('qty') or 0))
    if qty<=0 or not qty.is_finite():raise ValueError('Cantidad Paper positiva requerida.')
    current=next((p for p in positions if p.get('symbol')==symbol),None)
    if current:
        held=Decimal(str(current.get('qty') or 0))
        if ((held>0 and side=='sell') or (held<0 and side=='buy')) and qty<=abs(held):return
    if orders:raise ValueError('Reconcilia órdenes pendientes antes de aumentar exposición del presupuesto.')
    invested=sum(abs(Decimal(str(p.get('market_value') or 0))) for p in positions)
    unit=Decimal(str(price))
    if not unit.is_finite() or unit<=0:raise ValueError('Precio verificable requerido para presupuesto Paper.')
    if invested+qty*unit>assigned(d):raise ValueError('Risk: exposición supera capital explícitamente asignado.')
