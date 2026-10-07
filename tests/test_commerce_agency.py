"""Focused offline Commerce/CRM tests. No actual money, orders or outreach."""
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from app import holdings,business_orchestration as control,commerce_workspace as commerce,agency_crm as agency
from app.commerce_pricing import pricing,score,COSTS,WEIGHTS
from app.commerce_adapters import ShopifyAdapter,SupplierAdapter,PRODUCTS,SHOP

class FakeShop:
    def verify(self):return {'shop':{'id':'gid://shopify/Shop/offline','currencyCode':'EUR'}}
    def collection(self,kind):
        if kind=='products':return []
        if kind=='customers':return [{'id':'customer-offline','displayName':'Offline'}]
        return [{'id':'gid://shopify/Order/offline','name':'#OFFLINE','displayFinancialStatus':'PAID',
            'displayFulfillmentStatus':'UNFULFILLED','currentTotalPriceSet':{'shopMoney':{'amount':'60','currencyCode':'EUR'}},
            'totalRefundedSet':{'shopMoney':{'amount':'0','currencyCode':'EUR'}},
            'lineItems':{'nodes':[{'id':'line-offline','quantity':2,'variant':{'sku':'OFFLINE-SKU'}}],'pageInfo':{'hasNextPage':False}},
            'fulfillmentOrders':{'nodes':[{'id':'fulfillment-order-offline','status':'OPEN',
                'lineItems':{'nodes':[{'id':'fulfillment-line-offline','remainingQuantity':2,'lineItem':{'id':'line-offline'}}]}}]}}]
    def draft(self,listing):return {'id':'gid://shopify/Product/offline','status':'DRAFT'}
    def publish(self,*args):return {'status':'PUBLISHED'}
    def fulfill(self,value):return {'id':'fulfillment-offline','status':'SUCCESS'}

class Response:
    ok=True;status_code=200
    def __init__(self,value):self.value=value
    def json(self):return self.value

class Session:
    def __init__(self,values):self.values=list(values);self.calls=[]
    def post(self,url,**kwargs):self.calls.append((url,kwargs));return Response(self.values.pop(0))
    def get(self,url,**kwargs):self.calls.append((url,kwargs));return Response(self.values.pop(0))

class BusinessTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1];self.tmp=self.root/('zar-commerce-test-'+uuid.uuid4().hex);self.tmp.mkdir()
        self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':str(self.tmp)},clear=True);self.env.start();self.scope='offline-business'
    def tearDown(self):
        self.env.stop();assert self.tmp.resolve().is_relative_to(self.root);shutil.rmtree(self.tmp)
    def costs(self):return {'sale_price':'30','currency':'EUR',**{k:0 for k in COSTS},'product_cost':10,'shipping':3}
    def product(self):
        supplier=commerce.operate(self.scope,'supplier',{'name':'Offline supplier supplied by test','model':'DROPSHIPPING','supports_dropshipping':True})
        product=commerce.operate(self.scope,'product',{'name':'Drawer organizer','supplier_id':supplier['id'],'supplier_sku':'OFFLINE-SKU','currency':'EUR','dropshipping':True})
        commerce.operate(self.scope,'pricing',{'product_id':product['id'],**self.costs()})
        commerce.operate(self.scope,'product_state',{'product_id':product['id'],'state':'APPROVED','confirmed':True})
        return supplier,product
    def order(self):
        with patch.object(commerce,'ShopifyAdapter',return_value=FakeShop()):commerce.operate(self.scope,'shopify_sync',{})
        return commerce.view(self.scope)['orders'][0]
    def quote(self,order,product):
        value={'reference':'quote-offline','sku':'OFFLINE-SKU','quantity':2,'currency':'EUR','product_cost':'20','shipping':'3','taxes':'2','fees':'0','total':'25',
            'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        with patch.object(SupplierAdapter,'quote',return_value=value):
            return commerce.operate(self.scope,'quote',{'order_id':order['id'],'product_id':product['id'],'quantity':2,'country':'ES'})
    def approved_order(self):
        supplier,product=self.product();order=self.order();q=self.quote(order,product)
        control.mutate(self.scope,'mode',{'mode':'SUPERVISED'})
        control.mutate(self.scope,'deposit',{'amount':'100','currency':'EUR','reference':'offline-funding'})
        result=commerce.operate(self.scope,'order_prepare',{'quote_id':q['id']})
        approval=result['approval'];control.mutate(self.scope,'approve',{'id':approval['id'],'total':approval['total'],'confirmed':True})
        return order,q,approval
    def execution(self,order):return {'order_id':order['id'],'confirmed':True,'total':'25.00',
        'shipping_address':{'name':'Offline customer','address1':'Offline street','city':'Offline city','postal_code':'00000','country':'ES'}}
    def test_niches_editable_and_persisted(self):
        view=commerce.view(self.scope);self.assertEqual(len(view['niches']),11)
        first=view['niches'][0]
        commerce.operate(self.scope,'niche',{'id':first['id'],'name':'Custom niche','subniches':['Custom']})
        self.assertEqual(commerce.view(self.scope)['niches'][0]['name'],'Custom niche')
        self.assertEqual(len(commerce.view('other')['niches']),11)
    def test_pricing_unknowns_and_visible_assumptions(self):
        result=pricing({'sale_price':30,'currency':'EUR','product_cost':10})
        self.assertIsNone(result['estimated_profit']);self.assertIn('shipping',result['unknown_costs'])
        result=pricing(self.costs());self.assertEqual(result['estimated_profit'],'17.00');self.assertEqual(result['minimum_price'],'13.00')
        self.assertEqual(result['recommended_price'],'18.57');self.assertEqual(result['break_even_roas'],'1.76')
        for bad in [True,'NaN',-1,'Infinity']:
            with self.assertRaises(ValueError):pricing({**self.costs(),'shipping':bad})
    def test_transparent_scoring_requires_evidence_and_full_coverage(self):
        evidence={'margin':{'value':.8,'classification':'ESTIMADA','source':'pricing assumptions'}}
        result=score(evidence);self.assertIsNone(result['score']);self.assertEqual(result['known_points'],'16.00');self.assertEqual(result['coverage'],20)
        result=score({k:{'value':1,'classification':'ESTIMADA','source':'offline assumption'} for k in WEIGHTS})
        self.assertEqual(result['score'],'100.00');self.assertEqual(len(result['breakdown']),15)
        with self.assertRaises(ValueError):score({'demand':{'value':.8,'classification':'REAL'}})
    def test_research_no_invented_market_numbers(self):
        niche=commerce.view(self.scope)['niches'][0]
        with patch('app.web_search._public_search',return_value={'results':[{'title':'Offline source','url':'https://example.invalid'}]}):
            row=commerce.operate(self.scope,'research',{'niche_id':niche['id']})
        self.assertTrue(all(x['classification']=='NO DISPONIBLE' for x in row['metrics'].values()))
        self.assertEqual(len(row['sources']),1)
    def test_supplier_capability_not_assumed_and_quote_line_match(self):
        supplier,product=self.product();order=self.order()
        with self.assertRaises(ValueError):commerce.operate(self.scope,'quote',{'order_id':order['id'],'product_id':product['id'],'quantity':1,'country':'ES'})
        c=holdings.read(self.scope);c['commerce_workspace']['suppliers'][0]['supports_dropshipping']=False;holdings.write(self.scope,c)
        with self.assertRaises(ValueError):self.quote(order,product)
    def test_real_purchase_requires_wallet_approval_and_bound_quote(self):
        supplier,product=self.product();order=self.order();q=self.quote(order,product)
        commerce.operate(self.scope,'order_prepare',{'quote_id':q['id']})
        with patch.object(SupplierAdapter,'order') as external:
            with self.assertRaises(ValueError):commerce.operate(self.scope,'order_execute',self.execution(order))
            external.assert_not_called()
    def test_supplier_order_idempotency_and_actual_cost_settles_reservation(self):
        order,q,approval=self.approved_order()
        self.assertEqual(control.view(self.scope)['wallet']['balances']['EUR']['available'],'75.00')
        result={'id':'order-offline','quote_reference':'quote-offline','status':'ORDERED','currency':'EUR','total':'25','charged':True,'charged_amount':'25','receipt_reference':'receipt-offline'}
        with patch.object(SupplierAdapter,'order',return_value=result) as external:
            commerce.operate(self.scope,'order_execute',self.execution(order))
            commerce.operate(self.scope,'order_execute',self.execution(order))
            self.assertEqual(external.call_count,1)
        balances=control.view(self.scope)['wallet']['balances']['EUR'];self.assertEqual(Decimal(balances['available']),Decimal('75.00'));self.assertEqual(Decimal(balances['committed']),Decimal('0.00'))
        self.assertEqual(len(holdings.read(self.scope)['ledger']),2)
    def test_ambiguous_order_keeps_reservation_and_never_reposts(self):
        order,q,approval=self.approved_order()
        with patch.object(SupplierAdapter,'order',side_effect=TimeoutError) as external:
            with self.assertRaises(ValueError):commerce.operate(self.scope,'order_execute',self.execution(order))
            result=commerce.operate(self.scope,'order_execute',self.execution(order));self.assertEqual(result['state'],'REVIEW_REQUIRED');self.assertEqual(external.call_count,1)
        self.assertEqual(control.view(self.scope)['wallet']['balances']['EUR']['committed'],'25.00')
        with self.assertRaises(ValueError):control.mutate(self.scope,'cancel',{'id':approval['id']})
    def test_supplier_config_change_blocks_execution(self):
        order,q,approval=self.approved_order()
        with patch.dict(os.environ,{'ZAR_SUPPLIER_ORDER_WEBHOOK':'https://changed.invalid'}),patch.object(SupplierAdapter,'order') as external:
            with self.assertRaises(ValueError):commerce.operate(self.scope,'order_execute',self.execution(order))
            external.assert_not_called()
    def test_reconcile_lost_order_response_records_receipt_without_reposting(self):
        order,q,approval=self.approved_order()
        with patch.object(SupplierAdapter,'order',side_effect=TimeoutError):
            with self.assertRaises(ValueError):commerce.operate(self.scope,'order_execute',self.execution(order))
        result={'id':'offline-order','status':'ORDERED','idempotency_key':'zar-order-'+order['id'],'quote_reference':q['reference'],
            'currency':'EUR','total':'25','charged':True,'charged_amount':'25','receipt_reference':'offline-receipt'}
        with patch.object(SupplierAdapter,'call',return_value=result),patch.object(SupplierAdapter,'order') as external:
            commerce.operate(self.scope,'order_reconcile',{'order_id':order['id'],'confirmed':True})
            commerce.operate(self.scope,'order_reconcile',{'order_id':order['id'],'confirmed':True});external.assert_not_called()
        balances=control.view(self.scope)['wallet']['balances']['EUR']
        self.assertEqual(Decimal(balances['available']),Decimal('75'));self.assertEqual(Decimal(balances['committed']),Decimal('0'))
        self.assertEqual(len(holdings.read(self.scope)['ledger']),2)
    def test_reconcile_only_verified_cancel_without_charge_releases_funds(self):
        order,q,approval=self.approved_order()
        with patch.object(SupplierAdapter,'order',side_effect=TimeoutError):
            with self.assertRaises(ValueError):commerce.operate(self.scope,'order_execute',self.execution(order))
        result={'status':'NOT_FOUND','idempotency_key':'zar-order-'+order['id'],'quote_reference':q['reference'],'charged':False}
        with patch.object(SupplierAdapter,'call',return_value=result):
            with self.assertRaises(ValueError):commerce.operate(self.scope,'order_reconcile',{'order_id':order['id'],'confirmed':True})
            result['status']='CANCELLED';commerce.operate(self.scope,'order_reconcile',{'order_id':order['id'],'confirmed':True})
        self.assertEqual(Decimal(control.view(self.scope)['wallet']['balances']['EUR']['available']),Decimal('100'))
    def test_shopify_paid_orders_do_not_add_wallet_cash(self):
        order=self.order();self.order();self.assertEqual(len(commerce.view(self.scope)['orders']),1)
        self.assertEqual(holdings.read(self.scope)['ledger'],[])
        commerce.operate(self.scope,'receipt',{'order_id':order['id'],'amount':58,'currency':'EUR','bank_reference':'offline-bank','confirmed':True})
        commerce.operate(self.scope,'receipt',{'order_id':order['id'],'amount':58,'currency':'EUR','bank_reference':'offline-bank','confirmed':True})
        self.assertEqual(len(holdings.read(self.scope)['ledger']),1)
    def test_listing_preview_and_remote_intention(self):
        supplier,product=self.product()
        listing=commerce.operate(self.scope,'listing',{'product_id':product['id'],'description':'Original <safe> text'})
        self.assertIn('&lt;safe&gt;',listing['descriptionHtml'])
        with patch.object(commerce,'ShopifyAdapter',return_value=FakeShop()) as external:
            with self.assertRaises(ValueError):commerce.operate(self.scope,'shopify_draft',{'listing_id':listing['id']})
            control.mutate(self.scope,'mode',{'mode':'SUPERVISED'})
            commerce.operate(self.scope,'shopify_draft',{'listing_id':listing['id'],'confirmed':True})
            result=commerce.operate(self.scope,'shopify_draft',{'listing_id':listing['id'],'confirmed':True})
            self.assertEqual(result['state'],'CONFIRMED')
    def test_fulfillment_requires_actual_tracking_and_only_matched_line(self):
        order,q,approval=self.approved_order()
        with self.assertRaises(ValueError):commerce.operate(self.scope,'fulfill',{'order_id':order['id'],'confirmed':True,'fulfillment_order_ids':['fulfillment-order-offline']})
        d=holdings.read(self.scope);row=d['commerce_workspace']['orders'][0];row.update(state='SHIPPED',tracking={'number':'offline-tracking','company':'Offline carrier'});holdings.write(self.scope,d)
        fake=FakeShop()
        with patch.object(commerce,'ShopifyAdapter',return_value=fake),patch.object(fake,'fulfill',wraps=fake.fulfill) as external:
            commerce.operate(self.scope,'fulfill',{'order_id':order['id'],'confirmed':True,'fulfillment_order_ids':['fulfillment-order-offline']})
            commerce.operate(self.scope,'fulfill',{'order_id':order['id'],'confirmed':True,'fulfillment_order_ids':['fulfillment-order-offline']})
            self.assertEqual(external.call_count,1);self.assertFalse(external.call_args.args[0]['notifyCustomer'])
    def test_customer_service_escalates_and_does_not_send(self):
        order=self.order();result=commerce.operate(self.scope,'ticket',{'order_id':order['id'],'message':'Chargeback and legal complaint'})
        self.assertEqual(result['state'],'ESCALATED');self.assertFalse(result['sent'])
    def lead(self):return agency.operate(self.scope,'lead',{'name':'Offline garden shop','sector':'Jardinería','city':'Offline city','services':'Macetas y herramientas','email':'test@example.invalid'})
    def proposal(self,lead):return agency.operate(self.scope,'pricing',{'lead_id':lead['id'],'cost':100,'minimum':200,'target':300,'premium':400,'scope':'Demo y web revisadas; impuestos incluidos por supuesto explícito','taxes':0})
    def test_crm_demo_pricing_outreach_and_dnc(self):
        lead=self.lead();self.proposal(lead)
        demo=agency.operate(self.scope,'demo',{'lead_id':lead['id'],'price':300})
        path=self.tmp/'holdings_public_demos'/demo['slug']/'index.html';self.assertIn('Macetas y herramientas',path.read_text())
        draft=agency.operate(self.scope,'outreach',{'lead_id':lead['id']});self.assertIn('Somos ZAR Web Agency',draft['body']);self.assertFalse(draft['sent'])
        with self.assertRaises(ValueError):agency.operate(self.scope,'state',{'lead_id':lead['id'],'state':'CONTACTED'})
        agency.operate(self.scope,'state',{'lead_id':lead['id'],'state':'DO_NOT_CONTACT'})
        with self.assertRaises(ValueError):agency.operate(self.scope,'outreach',{'lead_id':lead['id']})
    def test_negotiation_never_crosses_floor_without_specific_approval(self):
        lead=self.lead();self.proposal(lead)
        with self.assertRaises(ValueError):agency.operate(self.scope,'negotiate',{'lead_id':lead['id'],'offer':199,'message':'Discount?'})
        result=agency.operate(self.scope,'negotiate',{'lead_id':lead['id'],'offer':250,'message':'Discount?'});self.assertEqual(result['offer'],'250.00')
    def test_payment_provider_confirmation_test_mode_and_wallet_receipt(self):
        lead=self.lead();p=self.proposal(lead)
        checkout={'provider_id':'cs_offline','url':'https://checkout.example.invalid/offline','state':'PENDING','amount':'300.00','currency':'EUR','test_mode':True,'provider':'Stripe'}
        with patch.object(agency.PaymentAdapter,'checkout',return_value=checkout):
            agency.operate(self.scope,'checkout',{'lead_id':lead['id'],'confirmed':True,'total':'300.00'})
        value={'id':'cs_offline','metadata':{'scope':self.scope,'lead':lead['id'],'proposal':p['id']},'amount_total':30000,'currency':'eur','payment_status':'paid','livemode':False}
        with patch.object(agency.PaymentAdapter,'payment',return_value=value):agency.operate(self.scope,'payment_sync',{'lead_id':lead['id']})
        with self.assertRaises(ValueError):agency.operate(self.scope,'receipt',{'lead_id':lead['id'],'amount':300,'bank_reference':'offline-bank','confirmed':True})
        value['livemode']=True
        with patch.object(agency.PaymentAdapter,'payment',return_value=value):agency.operate(self.scope,'payment_sync',{'lead_id':lead['id']})
        self.assertEqual(holdings.read(self.scope)['ledger'],[])
        agency.operate(self.scope,'receipt',{'lead_id':lead['id'],'amount':290,'bank_reference':'offline-bank','confirmed':True})
        agency.operate(self.scope,'receipt',{'lead_id':lead['id'],'amount':290,'bank_reference':'offline-bank','confirmed':True})
        self.assertEqual(len(holdings.read(self.scope)['ledger']),1)
    def test_automaton_local_pricing_and_shadow(self):
        supplier,product=self.product()
        control.mutate(self.scope,'mode',{'mode':'SHADOW'})
        control.mutate(self.scope,'task',{'agent':'PricingAgent','tool':'commerce_pricing','payload':{'product_id':product['id'],**self.costs()},'request_id':'offline-task'})
        control.tick(self.scope);self.assertEqual(control.view(self.scope)['tasks'][0]['state'],'QUEUED')
        control.mutate(self.scope,'mode',{'mode':'SUPERVISED'});control.tick(self.scope)
        self.assertEqual(control.view(self.scope)['tasks'][0]['state'],'DONE');self.assertTrue(holdings.read(self.scope)['jev_decisions'])
    def test_api_csrf_and_metadata_only_accounts(self):
        from flask import Flask
        from app.business_workflows import register
        app=Flask(__name__);app.secret_key='OFFLINE_ONLY';register(app,lambda:self.scope)
        with app.test_client() as client:
            self.assertEqual(client.post('/api/holdings/workflows/commerce_niche',json={'name':'Custom'}).status_code,403)
            state=client.get('/api/holdings/workflows').json
            result=client.post('/api/holdings/workflows/commerce_niche',json={'name':'Custom'},headers={'X-ZAR-Business-CSRF':state['csrf']})
            self.assertEqual(result.status_code,200);self.assertEqual(len(commerce.view(self.scope)['niches']),12)

    def test_shopify_adapter_contract_pagination_and_no_redirects(self):
        session=Session([{'data':{'shop':{'id':'offline-shop','currencyCode':'EUR'}}},
            {'data':{'products':{'nodes':[{'id':'offline-1'}],'pageInfo':{'hasNextPage':True,'endCursor':'offline-cursor'}}}},
            {'data':{'products':{'nodes':[{'id':'offline-2'}],'pageInfo':{'hasNextPage':False}}}}])
        with patch.dict(os.environ,{'SHOPIFY_SHOP_DOMAIN':'offline.myshopify.com','SHOPIFY_ADMIN_ACCESS_TOKEN':'OFFLINE_ONLY'}):
            adapter=ShopifyAdapter(session);self.assertEqual(adapter.verify()['shop']['id'],'offline-shop')
            self.assertEqual(len(adapter.collection('products')),2)
        self.assertTrue(all(x[1]['allow_redirects'] is False for x in session.calls))
        self.assertEqual(session.calls[-1][1]['json']['variables']['after'],'offline-cursor')

    def test_shopify_adapter_refuses_arbitrary_hosts_and_graphql_errors(self):
        session=Session([{'errors':[{'message':'OFFLINE_SECRET_MUST_NOT_LEAK'}]}])
        with patch.dict(os.environ,{'SHOPIFY_SHOP_DOMAIN':'evil.invalid','SHOPIFY_ADMIN_ACCESS_TOKEN':'OFFLINE_ONLY'}):
            with self.assertRaises(ValueError):ShopifyAdapter(session).verify()
        self.assertEqual(session.calls,[])
        with patch.dict(os.environ,{'SHOPIFY_SHOP_DOMAIN':'offline.myshopify.com','SHOPIFY_ADMIN_ACCESS_TOKEN':'OFFLINE_ONLY'}):
            with self.assertRaises(ValueError) as exc:ShopifyAdapter(session).verify()
            self.assertNotIn('OFFLINE_SECRET',str(exc.exception))

    def test_shopify_draft_variants_images_and_copy_contract(self):
        session=Session([{'data':{'productSet':{'product':{'id':'offline-product','status':'DRAFT'},'userErrors':[]}}}])
        listing={'title':'Offline original','descriptionHtml':'<p>Original</p>','seo_title':'Original','meta_description':'Original',
            'price':'30','variants':[{'sku':'offline-red','price':'31','options':{'Color':'Red'}}],
            'images':['https://images.example.invalid/original.png'],'alt_text':'Original authorized photo'}
        with patch.dict(os.environ,{'SHOPIFY_SHOP_DOMAIN':'offline.myshopify.com','SHOPIFY_ADMIN_ACCESS_TOKEN':'OFFLINE_ONLY'}):ShopifyAdapter(session).draft(listing)
        value=session.calls[0][1]['json']['variables']['input'];self.assertEqual(value['status'],'DRAFT')
        self.assertEqual(value['variants'][0]['sku'],'offline-red');self.assertEqual(value['files'][0]['alt'],'Original authorized photo')

    def test_supplier_manual_and_stripe_checkout_contract(self):
        supplier={'id':'offline-supplier','env_prefix':'ZAR_SUPPLIER'}
        with self.assertRaises(ValueError) as exc:SupplierAdapter(supplier).quote({})
        self.assertIn('MANUAL_ACTION_REQUIRED',str(exc.exception))
        session=Session([{'id':'cs_offline','url':'https://checkout.example.invalid/offline','livemode':False}])
        lead=self.lead();proposal=self.proposal(lead)
        with patch.dict(os.environ,{'STRIPE_SECRET_KEY':'OFFLINE_ONLY','ZAR_CHECKOUT_SUCCESS_URL':'https://zar.example.invalid/success','ZAR_CHECKOUT_CANCEL_URL':'https://zar.example.invalid/cancel'}):
            result=agency.PaymentAdapter(session).checkout(self.scope,lead,proposal,'offline-idempotency')
        self.assertTrue(result['test_mode']);self.assertEqual(session.calls[0][1]['headers']['Idempotency-Key'],'offline-idempotency')
        self.assertEqual(session.calls[0][1]['data']['line_items[0][price_data][unit_amount]'],'30000')

if __name__=='__main__':unittest.main()
