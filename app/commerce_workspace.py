"""Commerce business records in the existing per-user Holdings transaction store."""
import html
import re
import uuid
import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal
from . import holdings,jev_decision,business_orchestration as control
from .commerce_pricing import pricing,score,number,fmt
from .commerce_adapters import ShopifyAdapter,SupplierAdapter,MODELS
from .business_connectors import verification

SEEDS=[('Organización del hogar',['cajas','separadores','organizadores de armario','ganchos','estantes pequeños','organizadores de cajones','almacenamiento bajo cama']),
 ('Fitness y recuperación',['foam rollers','bandas de resistencia','pelotas de masaje','movilidad','straps','recuperación']),
 ('Accesorios para mascotas',['organización','paseo','alimentación','juguetes simples','transporte','higiene']),
 ('Cocina',['organizadores','almacenamiento','utensilios simples','accesorios','preparación','limpieza']),
 ('Organización y accesorios de cocina',[]),('Jardinería',['herramientas pequeñas','macetas','organización','riego simple']),
 ('Accesorios simples para bebé',['organización de bajo riesgo']),('Belleza y cabello',['herramientas no reguladas','organización','cabello']),
 ('Accesorios para escritorio',[]),('Accesorios tecnológicos simples',['soportes','organización de cables']),('Viajes',['organizadores','bolsas','equipaje'])]
PRODUCT_STATES={'DISCOVERED','RESEARCHING','CANDIDATE','REJECTED','APPROVED','DRAFT_LISTING','PUBLISHED','ACTIVE','PAUSED','OUT_OF_STOCK','DISCONTINUED'}
RISK=re.compile(r'médic|medical|terapé|therap|sueño.*beb|baby.*sleep|seguridad crítica|safety critical|réplica|replica|falsific|certificación',re.I)

def ensure(d):
    c=d.setdefault('commerce_workspace',{})
    for name in ('niches','research','products','suppliers','quotes','listings','orders','fulfillments','customers','returns','tickets','operations'):
        c.setdefault(name,[])
    if not c.get('initialized'):
        c['niches']=[{'id':uuid.uuid4().hex,'name':name,'subniches':subs,'country':'ES','active':True,
            'budget':None,'minimum_margin':None,'target_price':None,'competition_tolerance':None,'max_shipping_days':None,
            'restrictions':['Sin claims médicos, seguridad crítica, falsificaciones ni certificaciones no verificadas'],'created_at':holdings._now()} for name,subs in SEEDS]
        c['initialized']=True
    return c

def find(rows,key):
    try:return next(x for x in rows if x['id']==key)
    except StopIteration:raise ValueError('Registro Commerce no encontrado.') from None

def text(value,limit=2000):return str(value or '').strip()[:limit]

def supplier_fingerprint(supplier):
    prefix=supplier['env_prefix']
    return hashlib.sha256(json.dumps([supplier['id'],supplier['model'],supplier.get('supports_dropshipping'),
        *[os.environ.get(prefix+'_'+suffix,'') for suffix in ('QUOTE_URL','ORDER_WEBHOOK','API_TOKEN')]]).encode()).hexdigest()

def economic_gate(scope,agent,task,action,cost=None,task_id=None):
    row=jev_decision.proposal(scope,{'source_agent':agent,'task':task,'task_id':task_id,'action':action,
        'expected_cost':cost,'expected_revenue':None,'risk':.4,'urgency':.5,'resources':['commerce']})
    if row['decision']=='REJECT':raise ValueError('JEV rechazó la operación.')
    return row

def audit(d,agent,action,item):
    c=ensure(d);c['operations'].append({'id':uuid.uuid4().hex,'timestamp':holdings._now(),'agent':agent,'action':action,'item':item})

def decision_outcome(d,decision,state):
    for row in d.get('jev_decisions',[]):
        if row['id']==decision['id']:row['subsequent_state']=state

def view(scope):
    with holdings.transaction(scope):
        d=holdings.read(scope);c=ensure(d);holdings.write(scope,d)
        result={**deepcopy(c),'dashboard':dashboard(d),'wallet':control.wallet(d)}
        for supplier in result['suppliers']:
            if supplier.get('state')=='LISTO':
                try:
                    age=(datetime.now(timezone.utc)-datetime.fromisoformat(supplier['checked_at'])).total_seconds()
                    if age>=600 or supplier.get('checked_fingerprint')!=supplier_fingerprint(supplier):supplier['state']='POR CONFIGURAR'
                except (KeyError,ValueError,TypeError):supplier['state']='POR CONFIGURAR'
        return result

def dashboard(d):
    c=ensure(d);groups={}
    for o in c['orders']:
        if o.get('financial_status') not in {'PAID','PARTIALLY_REFUNDED','REFUNDED'}:continue
        currency=o.get('currency');amount=number(o.get('current_total'))
        if not currency or amount is None:continue
        g=groups.setdefault(currency,{'sales':Decimal(0),'orders':0,'refunds':Decimal(0)})
        g['sales']+=amount;g['orders']+=1
        if o.get('refunded_amount') is not None:g['refunds']+=number(o['refunded_amount'])
    result={currency:{'sales':fmt(g['sales']),'orders':g['orders'],'average_order_value':fmt(g['sales']/g['orders']),
        'refunds':fmt(g['refunds']),'source':'Shopify order snapshot',
        'cash_received':fmt(sum(Decimal(str(x['amount'])) for x in d.get('ledger',[]) if x.get('company')=='commerce' and x.get('currency')==currency and x.get('kind')=='revenue' and x.get('status')=='collected')),
        'product_cost':None,'shipping':None,'advertising':None,'fees':None,'profit':None,'margin':None} for currency,g in groups.items()}
    return {'by_currency':result,'active_products':sum(x['state']=='ACTIVE' for x in c['products']),
        'best_product':None,'worst_product':None,'conversion':None,'note':'Pedidos pagados no equivalen a cobros bancarios. Sin atribución completa no se inventa beneficio.'}

def save_niche(c,data):
    row=find(c['niches'],data['id']) if data.get('id') else {'id':uuid.uuid4().hex,'created_at':holdings._now()}
    name=text(data.get('name') or row.get('name'),150)
    if not name:raise ValueError('Nombre de nicho requerido.')
    for field in ('budget','minimum_margin','target_price','max_shipping_days'):
        if field in data:row[field]=fmt(number(data[field]))
    for field in ('subniches','restrictions'):
        if field in data:
            if not isinstance(data[field],list) or len(data[field])>100:raise ValueError('Subnichos/restricciones requieren lista.')
            row[field]=[text(x,200) for x in data[field]]
    row.update(name=name,country=text(data.get('country') or row.get('country') or 'ES',30),
        active=data.get('active',row.get('active',True)) is True,competition_tolerance=text(data.get('competition_tolerance') or row.get('competition_tolerance'),100),updated_at=holdings._now())
    if not data.get('id'):c['niches'].append(row)
    return row

def supplier_record(c,data):
    row=find(c['suppliers'],data['id']) if data.get('id') else {'id':uuid.uuid4().hex,'created_at':holdings._now()}
    name=text(data.get('name'),150);model=data.get('model','MANUAL_FULFILLMENT');prefix=data.get('env_prefix') or 'ZAR_SUPPLIER'
    if not name or model not in MODELS or not re.fullmatch(r'ZAR_SUPPLIER(?:_[A-Z0-9_]{1,50})?',prefix):raise ValueError('Nombre/modelo/prefijo proveedor inválido.')
    row.update(name=name,model=model,env_prefix=prefix,source_url=text(data.get('source_url'),500),
        supports_dropshipping=data.get('supports_dropshipping') is True,shipping_countries=data.get('shipping_countries',[]),
        return_policy=text(data.get('return_policy')),branding_allowed=data.get('branding_allowed'),state='POR CONFIGURAR',updated_at=holdings._now())
    if not isinstance(row['shipping_countries'],list):raise ValueError('Países de envío requieren lista.')
    if not data.get('id'):c['suppliers'].append(row)
    return row

def product_record(c,data,*,source='user_input'):
    row=find(c['products'],data['id']) if data.get('id') else {'id':uuid.uuid4().hex,'state':'DISCOVERED','created_at':holdings._now()}
    if row['state'] in {'PUBLISHED','ACTIVE'}:raise ValueError('Pausa el producto antes de editar el candidato local.')
    name=text(data.get('name') or row.get('name'),200)
    if not name:raise ValueError('Nombre de producto requerido.')
    for k in ('category','supplier_sku','origin_country','return_policy','description','source_url','weight','dimensions'):
        if k in data:row[k]=text(data[k])
    for k in ('cost','shipping','moq','shipping_days','rating','stock','possible_sale_price'):
        if k in data:row[k]=fmt(number(data[k]))
    for k in ('delivery_countries','images','variants','risks'):
        if k in data:
            if not isinstance(data[k],list) or len(data[k])>100:raise ValueError('Campos de producto requieren listas de máximo 100 elementos.')
            row[k]=deepcopy(data[k])
    supplier=find(c['suppliers'],data['supplier_id']) if data.get('supplier_id') else None
    if data.get('currency') and not re.fullmatch(r'[A-Z]{3}',str(data['currency'])):raise ValueError('Moneda ISO requerida.')
    row.update(name=name,niche_id=data.get('niche_id',row.get('niche_id')),supplier_id=data.get('supplier_id',row.get('supplier_id')),
        currency=data.get('currency',row.get('currency')),model=supplier['model'] if supplier else row.get('model','MANUAL_FULFILLMENT'),
        dropshipping=data.get('dropshipping',row.get('dropshipping')),branding_allowed=data.get('branding_allowed',row.get('branding_allowed')),
        source=source,regulatory_review_required=bool(RISK.search(name+' '+row.get('description',''))) or data.get('regulatory_review_required') is True,
        updated_at=holdings._now())
    if row.get('niche_id'):find(c['niches'],row['niche_id'])
    if not data.get('id'):c['products'].append(row)
    return row

def research(scope,c,niche_id):
    niche=find(c['niches'],niche_id)
    from .web_search import _public_search
    result=_public_search(niche['name']+' '+niche['country']+' proveedores productos',8)
    sources=[{'title':x.get('title'),'url':x.get('url'),'snippet':x.get('snippet')} for x in result.get('results',[])]
    row={'id':uuid.uuid4().hex,'niche_id':niche_id,'input':deepcopy(niche),'timestamp':holdings._now(),
        'metrics':{k:{'value':None,'classification':'NO DISPONIBLE','source':None} for k in ('demand','trend','competition','seasonality','average_ticket')},
        'sources':sources,'candidates':[],'risks':list(niche.get('restrictions',[])),
        'recommendation':'Revisar fuentes, compatibilidad de proveedor y costes antes de seleccionar; búsqueda pública no demuestra demanda.'}
    c['research'].append(row);return row

def scout(c,supplier_id,query,niche_id=None):
    supplier=find(c['suppliers'],supplier_id);rows=SupplierAdapter(supplier).catalog(text(query,200));created=[]
    for item in rows:
        if not isinstance(item,dict) or not item.get('sku') or not item.get('name'):continue
        existing=next((x for x in c['products'] if x.get('supplier_id')==supplier_id and x.get('supplier_sku')==item['sku']),None)
        if existing:created.append(existing);continue
        product=product_record(c,{**item,'supplier_sku':item['sku'],'supplier_id':supplier_id,'niche_id':niche_id},source='supplier_catalog')
        product['catalog_checked_at']=holdings._now();product['state']='CANDIDATE';created.append(product)
    supplier.update(state='LISTO',checked_at=holdings._now(),checked_fingerprint=supplier_fingerprint(supplier),verification_scope='catalog read; no quote/order guarantee')
    return created

def listing(c,product_id,data):
    product=find(c['products'],product_id)
    if product['state'] not in {'APPROVED','DRAFT_LISTING'}:raise ValueError('Aprobar candidato antes de crear listing.')
    p=product.get('pricing')
    if not p or p['unknown_costs']:raise ValueError('Completa costes/supuestos antes de preparar listing.')
    title=text(data.get('title') or product['name'],200)
    description=text(data.get('description'),10000)
    if not description:raise ValueError('Texto original revisado requerido; no copiar descripción de terceros.')
    row={'id':uuid.uuid4().hex,'product_id':product_id,'state':'DRAFT_LISTING','title':title,
        'descriptionHtml':'<p>'+html.escape(description).replace('\n','</p><p>')+'</p>',
        'bullets':data.get('bullets',[]),'seo_title':text(data.get('seo_title') or title,70),
        'meta_description':text(data.get('meta_description') or description,160),'tags':data.get('tags',[]),
        'collection':text(data.get('collection'),150),'variants':deepcopy(product.get('variants',[])),
        'price':p['sale_price'],'currency':p['currency'],'compare_at_price':fmt(number(data.get('compare_at_price'))),
        'sku':product.get('supplier_sku'),'images':deepcopy(product.get('images',[])),'alt_text':text(data.get('alt_text') or title,200),
        'shipping_policy':text(data.get('shipping_policy') or product.get('return_policy')),'faq':text(data.get('faq')),
        'created_at':holdings._now(),'external_intent':None,'shopify_id':None}
    if row['compare_at_price'] and Decimal(row['compare_at_price'])<=Decimal(row['price']):raise ValueError('Compare-at debe superar precio; requiere precio anterior justificable.')
    for key in ('tags','bullets'):
        if not isinstance(row[key],list):raise ValueError('Tags/bullets requieren lista.')
    if row['bullets']:row['descriptionHtml']+='<ul>'+''.join('<li>'+html.escape(text(x))+'</li>' for x in row['bullets'])+'</ul>'
    if row['shipping_policy']:row['descriptionHtml']+='<h3>Envío y devoluciones</h3><p>'+html.escape(row['shipping_policy'])+'</p>'
    if row['faq']:row['descriptionHtml']+='<h3>FAQ</h3><p>'+html.escape(row['faq'])+'</p>'
    c['listings'].append(row);product['state']='DRAFT_LISTING';return row

def sync_shopify(c):
    adapter=ShopifyAdapter();verified=adapter.verify()
    products=adapter.collection('products');orders=adapter.collection('orders')
    c['shopify']={'shop':verified['shop'],'scopes':verified.get('currentAppInstallation',{}).get('accessScopes',[]),
        'products':products,'synced_at':holdings._now(),'metrics_source':'Shopify Admin GraphQL'}
    for raw in orders:
        ref=raw['id'];previous=next((o for o in c['orders'] if o.get('shopify_id')==ref),None)
        current=raw.get('currentTotalPriceSet',{}).get('shopMoney',{});refund=raw.get('totalRefundedSet',{}).get('shopMoney',{})
        financial=raw.get('displayFinancialStatus')
        row=previous or {'id':uuid.uuid4().hex,'created_at':holdings._now(),'state':'NEW','source':'Shopify Admin GraphQL'}
        row.update(shopify_id=ref,name=raw.get('name'),financial_status=financial,fulfillment_status=raw.get('displayFulfillmentStatus'),
            current_total=fmt(number(current.get('amount'))),currency=current.get('currencyCode'),refunded_amount=fmt(number(refund.get('amount'))),
            line_items=raw.get('lineItems',{}),fulfillment_orders=raw.get('fulfillmentOrders',{}),synced_at=holdings._now())
        if row['state'] in {'NEW','PAID','REFUNDED'}:row['state']='REFUNDED' if financial=='REFUNDED' else 'PAID' if financial in {'PAID','PARTIALLY_REFUNDED'} else 'NEW'
        if not previous:c['orders'].append(row)
    return {'orders_checked':len(orders),'ledger_added':0,'note':'Ventas observadas; cobro disponible requiere referencia de recepción. No se acredita total de pedido como payout.'}

def quote(c,data):
    order=find(c['orders'],data['order_id']);product=find(c['products'],data['product_id']);supplier=find(c['suppliers'],product['supplier_id'])
    quantity=data.get('quantity')
    if isinstance(quantity,bool) or not isinstance(quantity,int) or not 1<=quantity<=10000:raise ValueError('Cantidad entera positiva requerida.')
    if order['state'] not in {'PAID','SUPPLIER_PENDING'}:raise ValueError('Pedido pagado requerido para fulfillment.')
    lines=order.get('line_items',{})
    match=[x for x in lines.get('nodes',[]) if (x.get('variant') or {}).get('sku')==product.get('supplier_sku')]
    if lines.get('pageInfo',{}).get('hasNextPage') or len(match)!=1 or match[0]['quantity']!=quantity:
        raise ValueError('Quote requiere SKU/cantidad exactos de una línea Shopify completa.')
    if supplier['model'] not in {'DROPSHIPPING','PRINT_ON_DEMAND'} or supplier.get('supports_dropshipping') is not True or product.get('dropshipping') is not True:
        raise ValueError('MANUAL_ACTION_REQUIRED: envío directo no confirmado para proveedor y producto.')
    value=SupplierAdapter(supplier).quote({'sku':product.get('supplier_sku'),'quantity':quantity,'country':data.get('country')})
    if value.get('sku')!=product.get('supplier_sku') or value.get('quantity')!=quantity or not value.get('reference'):raise ValueError('Quote no corresponde al SKU/cantidad solicitado.')
    costs={k:number(value.get(k),required=True) for k in ('product_cost','shipping','taxes','fees','total')}
    if costs['total']<=0 or costs['total']!=sum(costs[k] for k in ('product_cost','shipping','taxes','fees')):raise ValueError('Total quote no coincide con desglose completo.')
    if any(v!=v.quantize(Decimal('.01')) for v in costs.values()):raise ValueError('Quote requiere importes exactos de máximo dos decimales.')
    expires=datetime.fromisoformat(value.get('expires_at',''))
    if expires.tzinfo is None or expires<=datetime.now(timezone.utc):raise ValueError('Quote caducado/sin zona horaria.')
    currency=value.get('currency')
    if not re.fullmatch(r'[A-Z]{3}',str(currency)):raise ValueError('Moneda quote requerida.')
    row={'id':uuid.uuid4().hex,'supplier_id':supplier['id'],'product_id':product['id'],'order_id':order['id'],
        'reference':text(value['reference'],200),'sku':product['supplier_sku'],'quantity':quantity,'currency':currency,
        'country':text(data.get('country'),30),'expires_at':expires.isoformat(),'verified_at':holdings._now(),**{k:fmt(v) for k,v in costs.items()}}
    row.update(line_item_id=match[0]['id'],supplier_fingerprint=supplier_fingerprint(supplier))
    c['quotes'].append(row);return row

def receipt(scope,c,data):
    order=find(c['orders'],data['order_id'])
    if data.get('confirmed') is not True or not text(data.get('bank_reference'),200):raise ValueError('Confirma cobro realmente recibido y referencia bancaria.')
    amount=number(data.get('amount'),required=True);currency=data.get('currency')
    if not amount or currency!=order.get('currency'):raise ValueError('Cobro positivo en la moneda del pedido requerido.')
    if order.get('receipt'):
        if order['receipt']['amount']!=fmt(amount) or order['receipt']['bank_reference']!=text(data['bank_reference'],200):raise ValueError('Cobro ya registrado con otro importe/referencia.')
        return order['receipt']
    if order.get('financial_status') not in {'PAID','PARTIALLY_REFUNDED'}:raise ValueError('Pedido Shopify pagado requerido.')
    if amount>number(order.get('current_total'),required=True):raise ValueError('Cobro no puede superar importe actual del pedido.')
    row=holdings.add_ledger(scope,'commerce','revenue',fmt(amount),currency=currency,source='commerce_received',
        reference=order['shopify_id'],note='Recepción manual confirmada: '+text(data['bank_reference'],200),verified=True)
    order['receipt']={'amount':fmt(amount),'currency':currency,'bank_reference':text(data['bank_reference'],200),'timestamp':holdings._now()}
    return order['receipt']

def optimization(c):
    rows=[]
    for product in c['products']:
        p=product.get('pricing') or {};steps=[]
        if product.get('stock') is not None and Decimal(product['stock'])<=0:steps.append('Pausar: stock proveedor cero confirmado en último catálogo')
        if p.get('estimated_profit') is not None and Decimal(p['estimated_profit'])<=0:steps.append('Revisar precio/costes: beneficio estimado no positivo')
        if p.get('unknown_costs'):steps.append('Completar costes desconocidos antes de decidir')
        rows.append({'product_id':product['id'],'recommendations':steps,'conversion':None,'cac':None,'actual_profit':None,
            'estimated_profit':p.get('estimated_profit'),'metrics_source':'pricing assumptions / supplier snapshot'})
    return {'timestamp':holdings._now(),'products':rows,'external_actions':False}

def operate(scope,action,data):
    if not isinstance(data,dict):raise ValueError('Objeto JSON requerido.')
    with holdings.transaction(scope):
        d=holdings.read(scope);c=ensure(d)
        result=None
        if action=='niche':result=save_niche(c,data)
        elif action=='supplier':result=supplier_record(c,data)
        elif action=='product':result=product_record(c,data)
        elif action=='research':result=research(scope,c,data['niche_id'])
        elif action=='scout':result=scout(c,data['supplier_id'],data.get('query'),data.get('niche_id'))
        elif action=='pricing':
            product=find(c['products'],data['product_id']);product['pricing']=pricing(data);result=product['pricing']
        elif action=='score':
            product=find(c['products'],data['product_id']);product['score']=score(data.get('evidence',{}));result=product['score']
        elif action=='product_state':
            product=find(c['products'],data['product_id']);target=data['state']
            if target not in {'RESEARCHING','CANDIDATE','REJECTED','APPROVED','PAUSED','DISCONTINUED'}:raise ValueError('Estado remoto requiere confirmación del proveedor/Shopify.')
            if target=='APPROVED':
                if data.get('confirmed') is not True or not product.get('supplier_id') or not product.get('pricing') or product['pricing']['unknown_costs']:
                    raise ValueError('Aprobación explícita con proveedor y costes completos requerida.')
                if product.get('regulatory_review_required') and not text(data.get('review_evidence')):raise ValueError('Producto de riesgo: evidencia de revisión/certificación requerida.')
                product['review_evidence']=text(data.get('review_evidence'))
            if product['state'] in {'ACTIVE','PUBLISHED'}:raise ValueError('Usa pausa Shopify explícita para sincronizar el estado remoto.')
            product['state']=target;result=product
        elif action=='listing':result=listing(c,data['product_id'],data)
        elif action=='shopify_sync':
            result=sync_shopify(c);d.setdefault('verified_connectors',{})['Shopify']=verification('Shopify','LISTO','shop, products and orders read')
            from .business_orchestration import note_verified_account
            shop=c['shopify']['shop']
            note_verified_account(d,'Shopify',shop.get('myshopifyDomain') or shop['id'],'SHOPIFY_ADMIN_ACCESS_TOKEN','shop, products and orders read')
        elif action=='shopify_customers':
            c['customers']=ShopifyAdapter().collection('customers');result=c['customers']
        elif action=='shopify_publications':result=ShopifyAdapter().publications()
        elif action in {'shopify_draft','shopify_publish'}:
            record=find(c['listings'],data['listing_id'])
            if data.get('confirmed') is not True:raise ValueError('Confirma escritura externa en Shopify.')
            if control.ensure(d)['agents'].get('ListingAgent',{}).get('state') in {'OFF','PAUSED'}:raise ValueError('ListingAgent pausado/apagado.')
            if d.get('global_stop') or control.ensure(d)['mode'] in {'OFF','SHADOW'}:raise ValueError('Operación bloqueada por STOP/modo Automaton.')
            product=find(c['products'],record['product_id'])
            if product['state'] not in {'DRAFT_LISTING','PUBLISHED','ACTIVE'}:raise ValueError('Candidato no aprobado para catálogo.')
            key=action+':'+record['id']+(':'+text(data.get('publication_id'),150) if action=='shopify_publish' else '')
            if key in (record.get('intents') or {}):return record['intents'][key]
            if action=='shopify_publish' and (not record.get('shopify_id') or not data.get('publication_id')):raise ValueError('Borrador remoto y publicación Shopify seleccionada requeridos.')
            decision=economic_gate(scope,'ListingAgent',action,'Write reviewed Shopify listing',0)
            d['jev_decisions']=holdings.read(scope).get('jev_decisions',[])
            record.setdefault('intents',{})[key]={'state':'REQUESTED','timestamp':holdings._now()};holdings.write(scope,d)
            try:
                if action=='shopify_draft':
                    shop=ShopifyAdapter().verify()['shop']
                    if shop['currencyCode']!=record['currency']:raise ValueError('Moneda de listing distinta de la tienda; no convertir automáticamente.')
                    remote=ShopifyAdapter().draft(record)
                    if not remote.get('id') or remote.get('status')!='DRAFT':raise ValueError('Borrador Shopify no confirmado.')
                    record['shopify_id']=remote['id'];result=remote
                else:
                    result=ShopifyAdapter().publish(record['shopify_id'],data['publication_id'])
                    record['state']='PUBLISHED';product['state']='ACTIVE'
                record['intents'][key].update(state='CONFIRMED',result=result)
                decision_outcome(d,decision,'SHOPIFY_WRITE_CONFIRMED')
            except Exception:
                record['intents'][key]['state']='REVIEW_REQUIRED';decision_outcome(d,decision,'REVIEW_REQUIRED');holdings.write(scope,d)
                raise ValueError('Escritura Shopify ambigua/rechazada; revisar administrador antes de repetir.') from None
        elif action=='shopify_pause':
            if data.get('confirmed') is not True or d.get('global_stop'):raise ValueError('Confirma pausa externa y revisa STOP.')
            record=find(c['listings'],data['listing_id'])
            if not record.get('shopify_id'):raise ValueError('Producto remoto requerido.')
            result=ShopifyAdapter().pause(record['shopify_id']);find(c['products'],record['product_id'])['state']='PAUSED'
        elif action=='quote':result=quote(c,data)
        elif action=='order_prepare':
            q=find(c['quotes'],data['quote_id']);order=find(c['orders'],q['order_id'])
            if datetime.fromisoformat(q['expires_at'])<=datetime.now(timezone.utc):raise ValueError('Quote caducado.')
            old=next((x for x in control.ensure(d)['approvals'] if x['id']==order.get('approval_id')),None)
            if order.get('supplier_order') or order.get('supplier_intent') or (old and old['state'] not in {'CANCELLED','REJECTED'}):
                raise ValueError('Pedido ya preparado/enviado; resolver antes de repetir.')
            decision=economic_gate(scope,'OrderAgent','Supplier order','Purchase quoted supplier order',q['total'],order['id'])
            d['jev_decisions']=holdings.read(scope).get('jev_decisions',[]);holdings.write(scope,d)
            control.mutate(scope,'prepare',{'item':q['quantity'].__str__()+' × '+q['sku'],'provider':q['supplier_id'],
                'price':fmt(Decimal(q['total'])-Decimal(q['taxes'])),'tax':q['taxes'],'currency':q['currency']})
            fresh=holdings.read(scope);d['orchestration']=fresh['orchestration']
            approval=d['orchestration']['approvals'][-1]
            approval.update(quote_id=q['id'],order_id=order['id'],expires_at=q['expires_at'],execution_state='AWAITING_APPROVAL',
                note='Quote proveedor confirmado; ejecución requiere aprobación/reserva Wallet y confirmación del total.')
            order.update(state='SUPPLIER_PENDING',quote_id=q['id'],approval_id=approval['id']);result={'order':order,'approval':approval,'jev_decision_id':decision['id']}
            decision_outcome(d,decision,'AWAITING_WALLET_APPROVAL')
        elif action=='order_execute':result=execute_order(scope,d,c,data)
        elif action=='order_reconcile':result=reconcile_order(scope,d,c,data)
        elif action=='tracking':result=tracking(c,data)
        elif action=='fulfill':result=fulfill(scope,d,c,data)
        elif action=='receipt':
            result=receipt(scope,c,data);d['ledger']=holdings.read(scope)['ledger']
        elif action=='optimization':c['optimization']=optimization(c);result=c['optimization']
        elif action=='compare':
            result={'quotes':deepcopy(c['quotes']),'ranking':None,
                'note':'Comparar moneda, SKU, cantidad, desglose, modelo y caducidad; no equiparar ofertas de productos diferentes.'}
        elif action=='ticket':result=ticket(c,data)
        elif action=='return':
            order=find(c['orders'],data['order_id']);row={'id':uuid.uuid4().hex,'order_id':order['id'],'state':'RETURN_REQUESTED',
                'reason':text(data.get('reason')),'created_at':holdings._now(),'refund':None};c['returns'].append(row);result=row
        else:raise ValueError('Operación Commerce no disponible.')
        audit(d,{'research':'NicheResearchAgent','scout':'ProductScoutAgent','pricing':'PricingAgent','quote':'SupplierAgent','listing':'ListingAgent'}.get(action,'Commerce'),action,data.get('product_id') or data.get('order_id'))
        holdings.write(scope,d);return deepcopy(result)

def execute_order(scope,d,c,data):
    order=find(c['orders'],data['order_id']);q=find(c['quotes'],order.get('quote_id'));supplier=find(c['suppliers'],q['supplier_id'])
    approval=find(control.ensure(d)['approvals'],order.get('approval_id'))
    if data.get('confirmed') is not True or str(data.get('total'))!=q['total']:raise ValueError('Confirmación explícita del total exacto requerida.')
    if any(control.ensure(d)['agents'].get(a,{}).get('state') in {'OFF','PAUSED'} for a in ('OrderAgent','FulfillmentAgent')):raise ValueError('OrderAgent/FulfillmentAgent pausado.')
    if order.get('supplier_intent'):return {'state':'REVIEW_REQUIRED','intent':order['supplier_intent'],'note':'No se reenvía intención ambigua.'}
    if d.get('global_stop') or control.ensure(d)['mode'] in {'OFF','SHADOW'} or approval['state']!='APPROVED':raise ValueError('Aprobación económica y reserva Wallet requeridas.')
    if Decimal(control.wallet(d)['balances'].get(q['currency'],{}).get('available','0'))<0:raise ValueError('Wallet ha cambiado y no cubre compromisos; no ejecutar.')
    if approval.get('quote_id')!=q['id'] or approval['total']!=q['total'] or approval['currency']!=q['currency'] or datetime.fromisoformat(q['expires_at'])<=datetime.now(timezone.utc):
        raise ValueError('Quote/aprobación cambiados o caducados; no ejecutar.')
    if q.get('supplier_fingerprint')!=supplier_fingerprint(supplier):raise ValueError('Configuración/proveedor cambiado desde quote; obtener nuevo presupuesto.')
    address=data.get('shipping_address')
    if not isinstance(address,dict) or any(not text(address.get(k),200) for k in ('name','address1','city','postal_code','country')):raise ValueError('Dirección revisada de envío requerida.')
    if address['country']!=q['country']:raise ValueError('País de entrega distinto del quote.')
    if supplier['model'] not in {'DROPSHIPPING','PRINT_ON_DEMAND'} or not supplier['supports_dropshipping']:raise ValueError('Proveedor no compatible con envío directo.')
    decision=economic_gate(scope,'FulfillmentAgent','Approved supplier purchase','Purchase bound approved supplier quote',q['total'],order['id'])
    d['jev_decisions']=holdings.read(scope).get('jev_decisions',[])
    intent={'idempotency_key':'zar-order-'+order['id'],'quote_reference':q['reference'],'timestamp':holdings._now(),'state':'REQUESTED'}
    order['supplier_intent']=intent;approval['execution_state']='REQUESTED';decision_outcome(d,decision,'USER_APPROVED_REQUESTED');holdings.write(scope,d)
    try:
        result=SupplierAdapter(supplier).order({'quote_reference':q['reference'],'sku':q['sku'],'quantity':q['quantity'],
            'currency':q['currency'],'total':q['total'],'shipping_address':address,'idempotency_key':intent['idempotency_key']})
        if not result.get('id') or result.get('quote_reference')!=q['reference'] or result.get('currency')!=q['currency'] or number(result.get('total'),required=True)!=Decimal(q['total']):raise ValueError('Pedido proveedor sin confirmación de referencia/total.')
        if result.get('status') not in {'ORDERED','SHIPPED'}:raise ValueError('Proveedor no confirmó pedido.')
        order['supplier_order']={'id':text(result['id'],200),'status':result['status'],'supplier_id':supplier['id'],'timestamp':holdings._now()}
        order['state']=result['status'];intent['state']='CONFIRMED';approval['execution_state']='ORDERED'
        if result.get('charged') is True:
            if not result.get('receipt_reference') or number(result.get('charged_amount'),required=True)!=Decimal(q['total']):raise ValueError('Coste real no reconciliado; revisar proveedor.')
            holdings.add_ledger(scope,'commerce','cost',q['total'],currency=q['currency'],source='supplier_receipt',
                reference=supplier['id']+':'+text(result['receipt_reference'],200),note='Quote '+q['reference'],verified=True)
            d['ledger']=holdings.read(scope)['ledger'];approval.update(state='SETTLED',execution_state='CHARGED')
        else:approval['execution_state']='ORDERED_AWAITING_RECEIPT'
        decision_outcome(d,decision,approval['execution_state'])
        return order
    except Exception:
        intent['state']='REVIEW_REQUIRED';approval['execution_state']='REVIEW_REQUIRED';decision_outcome(d,decision,'REVIEW_REQUIRED');holdings.write(scope,d)
        raise ValueError('Pedido/cobro no reconciliado: intención conservada, reserva retenida; revisar proveedor, no reenviar.') from None

def tracking(c,data):
    order=find(c['orders'],data['order_id']);external=order.get('supplier_order')
    if not external:raise ValueError('MANUAL_ACTION_REQUIRED: pedido proveedor no confirmado.')
    value=SupplierAdapter(find(c['suppliers'],external['supplier_id'])).tracking(external['id'])
    if value.get('order_id')!=external['id'] or value.get('status') not in {'ORDERED','SHIPPED','DELIVERED','ERROR'}:raise ValueError('Tracking no corresponde al pedido.')
    order.update(state=value['status'],tracking={'number':text(value.get('tracking_number'),200),'url':text(value.get('tracking_url'),1000),
        'company':text(value.get('carrier'),150),'checked_at':holdings._now()},issue=text(value.get('issue')))
    return order

def reconcile_order(scope,d,c,data):
    order=find(c['orders'],data['order_id']);intent=order.get('supplier_intent')
    if not intent or data.get('confirmed') is not True:raise ValueError('Confirma lectura/reconciliación de la intención ya enviada.')
    q=find(c['quotes'],order.get('quote_id'));supplier=find(c['suppliers'],q['supplier_id'])
    approval=find(control.ensure(d)['approvals'],order.get('approval_id'))
    if q['supplier_fingerprint']!=supplier_fingerprint(supplier):raise ValueError('Proveedor/configuración cambiado; reconciliación manual requerida.')
    result=SupplierAdapter(supplier).call('tracking',{'idempotency_key':intent['idempotency_key'],'quote_reference':q['reference']})
    if result.get('idempotency_key')!=intent['idempotency_key'] or result.get('quote_reference')!=q['reference']:
        raise ValueError('Respuesta no corresponde a la intención/quote; no liberar reserva.')
    state=result.get('status')
    if state=='CANCELLED' and result.get('charged') is False:
        if approval['state']=='SETTLED':raise ValueError('Existe cargo asentado; no tratarlo como cancelación sin cargo. Revisar reembolso real.')
        approval.update(state='CANCELLED',execution_state='CANCELLED_VERIFIED')
        order.setdefault('intent_history',[]).append(dict(intent,state='CANCELLED_VERIFIED',reconciled_at=holdings._now()))
        order.pop('supplier_intent',None);order.pop('supplier_order',None)
        order.update(state='PAID',approval_id=None,quote_id=None)
        return {'state':'CANCELLED_VERIFIED','note':'Cancelación sin cargo confirmada por proveedor; reserva liberada, no se reenvió pedido.'}
    if state not in {'ORDERED','SHIPPED','DELIVERED'} or not result.get('id') or result.get('currency')!=q['currency'] or number(result.get('total'),required=True)!=Decimal(q['total']):
        raise ValueError('Estado/total no confirmado; NOT_FOUND no demuestra ausencia de cargo. Reserva conservada.')
    order.update(state=state,supplier_order={'id':text(result['id'],200),'status':state,'supplier_id':supplier['id'],'timestamp':holdings._now()})
    intent.update(state='CONFIRMED',reconciled_at=holdings._now());approval['execution_state']='ORDERED_AWAITING_RECEIPT'
    if result.get('charged') is True:
        if not result.get('receipt_reference') or number(result.get('charged_amount'),required=True)!=Decimal(q['total']):raise ValueError('Recibo de cargo no coincide; no liberar reserva.')
        holdings.add_ledger(scope,'commerce','cost',q['total'],currency=q['currency'],source='supplier_receipt',
            reference=supplier['id']+':'+text(result['receipt_reference'],200),note='Cargo reconciliado del quote '+q['reference'],verified=True)
        d['ledger']=holdings.read(scope)['ledger'];approval.update(state='SETTLED',execution_state='CHARGED')
    if result.get('tracking_number'):
        order['tracking']={'number':text(result['tracking_number'],200),'company':text(result.get('carrier'),150),
            'url':text(result.get('tracking_url'),1000),'checked_at':holdings._now()}
    return order

def fulfill(scope,d,c,data):
    order=find(c['orders'],data['order_id'])
    if data.get('confirmed') is not True or d.get('global_stop') or control.ensure(d)['mode'] in {'OFF','SHADOW'}:raise ValueError('Confirma fulfillment externo; revisar modo/STOP.')
    if order['state'] not in {'SHIPPED','DELIVERED'} or not order.get('tracking',{}).get('number'):raise ValueError('Tracking real y envío confirmado requeridos.')
    if order.get('fulfillment_intent'):return order['fulfillment_intent']
    groups=order.get('fulfillment_orders',{})
    if groups.get('pageInfo',{}).get('hasNextPage'):raise ValueError('Fulfillment parcial no reconciliado; revisar Shopify.')
    selected=data.get('fulfillment_order_ids')
    if not isinstance(selected,list) or not selected:raise ValueError('Selecciona fulfillment orders revisados.')
    lines=[]
    quote_record=find(c['quotes'],order.get('quote_id'))
    for key in selected:
        group=next((x for x in groups.get('nodes',[]) if x['id']==key),None)
        if not group or group.get('status') not in {'OPEN','IN_PROGRESS'} or group.get('lineItems',{}).get('pageInfo',{}).get('hasNextPage'):raise ValueError('Fulfillment order no elegible/completo.')
        items=[{'id':x['id'],'quantity':x['remainingQuantity']} for x in group['lineItems']['nodes'] if x['remainingQuantity']>0 and x.get('lineItem',{}).get('id')==quote_record['line_item_id']]
        if not items:raise ValueError('Sin unidades pendientes.')
        lines.append({'fulfillmentOrderId':key,'fulfillmentOrderLineItems':items})
    if sum(x['quantity'] for group in lines for x in group['fulfillmentOrderLineItems'])!=quote_record['quantity']:
        raise ValueError('Unidades de fulfillment no coinciden con envío proveedor; no marcar otras líneas enviadas.')
    intent={'state':'REQUESTED','timestamp':holdings._now()};order['fulfillment_intent']=intent;holdings.write(scope,d)
    result=ShopifyAdapter().fulfill({'lineItemsByFulfillmentOrder':lines,'notifyCustomer':False,
        'trackingInfo':{'number':order['tracking']['number'],'company':order['tracking']['company']}})
    if not result.get('id'):raise ValueError('Fulfillment no confirmado; revisar Shopify sin repetir.')
    row={'id':result['id'],'order_id':order['id'],'provider':'Shopify','status':result.get('status'),'timestamp':holdings._now()}
    c['fulfillments'].append(row);intent.update(state='CONFIRMED',result=row);return row

def ticket(c,data):
    order=find(c['orders'],data['order_id']);message=text(data.get('message'),10000)
    if not message:raise ValueError('Consulta requerida.')
    escalation=bool(re.search(r'fraud|amenaz|threat|chargeback|legal|abogad|excepción|exception',message,re.I))
    response='Consulta escalada a Pablo; no se decide excepción ni reembolso.' if escalation else (
        'Estado registrado: '+order['state']+'. Tracking: '+text((order.get('tracking') or {}).get('number'))+'. Devoluciones sujetas a revisión de la política del pedido; no se ha emitido reembolso.')
    row={'id':uuid.uuid4().hex,'order_id':order['id'],'message':message,'reply_draft':response,
        'state':'ESCALATED' if escalation else 'DRAFT','history':[{'timestamp':holdings._now(),'direction':'INBOUND','text':message}],
        'sent':False,'created_at':holdings._now()};c['tickets'].append(row);return row
