"""Explicit decimal assumptions; unknown costs never become zero implicitly."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

COSTS=('product_cost','shipping','taxes','payment_fee','shopify_fee','supplier_fee','advertising','returns','other')

def number(value, *, required=False):
    if value is None or value=='':
        if required:raise ValueError('Importe conocido requerido.')
        return None
    if isinstance(value,bool):raise ValueError('Importe numérico requerido.')
    try:n=Decimal(str(value))
    except InvalidOperation:raise ValueError('Importe inválido.') from None
    if not n.is_finite() or n<0 or n>Decimal('1000000000'):raise ValueError('Importe finito no negativo requerido.')
    return n

def fmt(n):
    return None if n is None else str(Decimal(str(n)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))

def pricing(data):
    price=number(data.get('sale_price'),required=True)
    if not price:raise ValueError('Precio positivo requerido.')
    costs={k:number(data.get(k)) for k in COSTS}
    missing=[k for k,v in costs.items() if v is None]
    gross=None if costs['product_cost'] is None or costs['shipping'] is None else price-costs['product_cost']-costs['shipping']
    total=None if missing else sum(costs.values())
    profit=None if total is None else price-total
    non_ad=None if any(v is None for k,v in costs.items() if k!='advertising') else sum(v for k,v in costs.items() if k!='advertising')
    cac=None if non_ad is None else price-non_ad
    target=number(data.get('target_margin',30),required=True)
    premium=number(data.get('premium_margin',40),required=True)
    if target>=100 or premium>=100 or premium<target:raise ValueError('Márgenes objetivo/premium válidos requeridos.')
    currency=data.get('currency')
    if not isinstance(currency,str) or len(currency)!=3 or not currency.isalpha() or not currency.isupper():raise ValueError('Moneda ISO requerida.')
    return {'currency':currency,'sale_price':fmt(price),'assumptions':{k:fmt(v) for k,v in costs.items()},
        'unknown_costs':missing,'estimated_profit':fmt(profit),'gross_margin_pct':fmt(gross/price*100) if gross is not None else None,
        'net_margin_pct':fmt(profit/price*100) if profit is not None else None,'max_cac':fmt(cac),
        'break_even_roas':fmt(price/cac) if cac is not None and cac>0 else None,
        'minimum_price':fmt(total),'recommended_price':fmt(total/(1-target/100)) if total is not None else None,
        'premium_price':fmt(total/(1-premium/100)) if total is not None else None,
        'target_margin':fmt(target),'premium_margin':fmt(premium),'classification':'ESTIMADA',
        'method':'Costes por unidad; impuestos como importe explícito, no asesoría fiscal. Publicidad/devoluciones son supuestos.'}

WEIGHTS={'demand':15,'margin':20,'competition':10,'cost':5,'shipping':10,'supplier_reputation':10,
 'returns':5,'fragility':3,'saturation':4,'seasonality':3,'advertising_difficulty':3,
 'regulatory_risk':4,'ip_risk':4,'bundle':2,'upsell':2}

def score(evidence):
    rows=[]
    for key,weight in WEIGHTS.items():
        item=evidence.get(key) or {};value=number(item.get('value'))
        classification=item.get('classification','NO DISPONIBLE');source=item.get('source')
        if value is not None and (value>1 or classification not in {'REAL','ESTIMADA'} or not source):
            raise ValueError('Scoring: evidencia 0–1, clasificación y fuente requeridas. Mayor valor significa mejor aptitud.')
        rows.append({'factor':key,'weight':weight,'value':str(value) if value is not None else None,
            'points':fmt(value*weight) if value is not None else None,'classification':classification if value is not None else 'NO DISPONIBLE','source':source})
    coverage=sum(x['weight'] for x in rows if x['points'] is not None)
    points=sum(Decimal(x['points']) for x in rows if x['points'] is not None)
    return {'score':fmt(points) if coverage==100 else None,'known_points':fmt(points),'coverage':coverage,
        'maximum':100,'breakdown':rows,'method':'Suma de aptitud 0–1 × peso. Sin total comparable si faltan factores; no predice demanda.'}
