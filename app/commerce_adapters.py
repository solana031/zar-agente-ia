"""Shopify Admin GraphQL and an explicit private supplier bridge contract."""
import os
import re
from dataclasses import dataclass, asdict
from urllib.parse import urlparse
import requests
from .commerce_pricing import number,fmt

SHOP='query ZARShop { shop { id name currencyCode myshopifyDomain } currentAppInstallation { accessScopes { handle } } }'
PRODUCTS='query ZARCatalog($after:String) { products(first:20,after:$after) { nodes { id title status variants(first:20) { nodes { id sku price inventoryQuantity } pageInfo { hasNextPage } } } pageInfo { hasNextPage endCursor } } }'
ORDERS='''query ZARCommerceOrders($after:String) { orders(first:10,after:$after,sortKey:CREATED_AT,reverse:true) { nodes {
 id name createdAt displayFinancialStatus displayFulfillmentStatus
 currentTotalPriceSet { shopMoney { amount currencyCode } } totalRefundedSet { shopMoney { amount currencyCode } }
 lineItems(first:20) { nodes { id title quantity variant { id sku } } pageInfo { hasNextPage } }
 fulfillmentOrders(first:5) { nodes { id status lineItems(first:10) { nodes { id remainingQuantity lineItem { id } } pageInfo { hasNextPage } } } pageInfo { hasNextPage } }
 } pageInfo { hasNextPage endCursor } } }'''
CUSTOMERS='query ZARCustomers($after:String) { customers(first:100,after:$after) { nodes { id displayName } pageInfo { hasNextPage endCursor } } }'
PRODUCT_SET='mutation ZARDraft($input:ProductSetInput!) { productSet(input:$input,synchronous:true) { product { id title status variants(first:20) { nodes { id sku price } } } userErrors { field message } } }'
PRODUCT_UPDATE='mutation ZARProductStatus($product:ProductUpdateInput!) { productUpdate(product:$product) { product { id status } userErrors { field message } } }'
PUBLICATIONS='query ZARPublications { publications(first:100) { nodes { id name } pageInfo { hasNextPage } } }'
PUBLISH='mutation ZARPublish($id:ID!,$input:[PublicationInput!]!) { publishablePublish(id:$id,input:$input) { userErrors { field message } } }'
FULFILL='mutation ZARFulfill($fulfillment:FulfillmentInput!) { fulfillmentCreate(fulfillment:$fulfillment) { fulfillment { id status trackingInfo { number url company } } userErrors { field message } } }'

class ShopifyAdapter:
    def __init__(self,session=None):self.session=session or requests.Session()
    def graphql(self,query,variables=None):
        shop=os.environ.get('SHOPIFY_SHOP_DOMAIN','').strip().removeprefix('https://').rstrip('/')
        token=os.environ.get('SHOPIFY_ADMIN_ACCESS_TOKEN','').strip()
        version=os.environ.get('SHOPIFY_API_VERSION','2026-10')
        if not token or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com',shop):
            raise ValueError('POR CONFIGURAR: SHOPIFY_SHOP_DOMAIN (tienda.myshopify.com) y SHOPIFY_ADMIN_ACCESS_TOKEN.')
        if not re.fullmatch(r'20\d\d-(01|04|07|10)',version):raise ValueError('SHOPIFY_API_VERSION inválida.')
        r=self.session.post(f'https://{shop}/admin/api/{version}/graphql.json',
            headers={'X-Shopify-Access-Token':token},json={'query':query,'variables':variables or {}},timeout=(5,40),allow_redirects=False)
        if not r.ok:raise ValueError('Shopify no confirmó operación (HTTP '+str(r.status_code)+').')
        body=r.json()
        if body.get('errors') or not isinstance(body.get('data'),dict):raise ValueError('Shopify GraphQL no confirmó contrato/permisos; resultado no aplicado.')
        return body['data']
    def verify(self):
        data=self.graphql(SHOP)
        if not (data.get('shop') or {}).get('id'):raise ValueError('Shopify no confirmó tienda.')
        return data
    def collection(self,kind):
        query={'products':PRODUCTS,'orders':ORDERS,'customers':CUSTOMERS}[kind]
        rows=[];after=None
        for _ in range(30):
            data=self.graphql(query,{'after':after})[kind]
            rows.extend(data.get('nodes',[]));page=data.get('pageInfo',{})
            if not page.get('hasNextPage'):return rows
            cursor=page.get('endCursor')
            if not cursor or cursor==after:raise ValueError('Paginación Shopify incompleta; no aplicar snapshot.')
            after=cursor
        raise ValueError('Límite de paginación Shopify; no aplicar snapshot incompleto.')
    def mutate(self,query,variables,key):
        result=self.graphql(query,variables)[key]
        if result.get('userErrors'):raise ValueError('Shopify rechazó los campos/permisos; revisar en administrador.')
        return result
    def draft(self,listing):
        data={'title':listing['title'],'descriptionHtml':listing['descriptionHtml'],'status':'DRAFT','tags':listing.get('tags',[]),
            'seo':{'title':listing['seo_title'],'description':listing['meta_description']},
            'productOptions':[{'name':'Title','position':1,'values':[{'name':'Default Title'}]}],
            'variants':[{'price':listing['price'],'optionValues':[{'optionName':'Title','name':'Default Title'}],
                         'sku':listing.get('sku') or ''}]}
        variants=listing.get('variants') or []
        if variants:
            if any(not isinstance(v,dict) or not isinstance(v.get('options'),dict) or not v['options'] or not v.get('sku') for v in variants):
                raise ValueError('Variantes requieren sku, price y options {nombre:valor} revisados.')
            names=list(variants[0]['options'])
            if len(names)>3 or any(set(v['options'])!=set(names) for v in variants):raise ValueError('Opciones de variantes inconsistentes.')
            data['productOptions']=[{'name':name,'position':i+1,'values':[{'name':value} for value in dict.fromkeys(str(v['options'][name]) for v in variants)]} for i,name in enumerate(names)]
            data['variants']=[]
            for v in variants:
                price=number(v.get('price'),required=True)
                if not price:raise ValueError('Precio positivo por variante requerido.')
                data['variants'].append({'sku':str(v['sku']),'price':fmt(price),'optionValues':[{'optionName':name,'name':str(v['options'][name])} for name in names]})
        images=listing.get('images') or []
        if images:
            data['files']=[]
            for image in images:
                url=image.get('url') if isinstance(image,dict) else image
                p=urlparse(str(url or ''))
                if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Imagen requiere fuente HTTPS revisada y permiso de uso.')
                data['files'].append({'originalSource':url,'contentType':'IMAGE','alt':listing.get('alt_text') or listing['title']})
        if listing.get('collection'):
            if not re.fullmatch(r'gid://shopify/Collection/\d+',listing['collection']):raise ValueError('Colección remota requiere gid Shopify revisado; nombre local no equivale a colección conectada.')
            data['collections']=[listing['collection']]
        if listing.get('compare_at_price'):data['variants'][0]['compareAtPrice']=listing['compare_at_price']
        if listing.get('shopify_id'):data['id']=listing['shopify_id']
        return self.mutate(PRODUCT_SET,{'input':data},'productSet')['product']
    def publications(self):return self.graphql(PUBLICATIONS)['publications']
    def publish(self,product_id,publication_id):
        self.mutate(PRODUCT_UPDATE,{'product':{'id':product_id,'status':'ACTIVE'}},'productUpdate')
        self.mutate(PUBLISH,{'id':product_id,'input':[{'publicationId':publication_id}]},'publishablePublish')
        return {'id':product_id,'publication_id':publication_id,'status':'PUBLISHED'}
    def pause(self,product_id):return self.mutate(PRODUCT_UPDATE,{'product':{'id':product_id,'status':'DRAFT'}},'productUpdate')['product']
    def fulfill(self,fulfillment):return self.mutate(FULFILL,{'fulfillment':fulfillment},'fulfillmentCreate')['fulfillment']

MODELS={'DROPSHIPPING','WHOLESALE','PRINT_ON_DEMAND','MARKETPLACE','MANUAL_FULFILLMENT','NO_COMPATIBLE'}

@dataclass
class SupplierProduct:
    sku:str
    name:str
    currency:str|None=None
    cost:str|None=None
    shipping:str|None=None
    model:str='MANUAL_FULFILLMENT'
    dropshipping:bool|None=None
    stock:int|None=None

@dataclass
class SupplierQuote:
    reference:str
    currency:str
    product_cost:str
    shipping:str
    taxes:str
    total:str
    quantity:int
    expires_at:str

@dataclass
class SupplierOrder:
    id:str
    status:str
    currency:str|None=None
    charged_amount:str|None=None
    receipt_reference:str|None=None

class SupplierAdapter:
    """No API capability inferred from model or a catalog URL."""
    def __init__(self,supplier,session=None):self.supplier=supplier;self.session=session or requests.Session()
    def configured(self,operation):
        prefix=self.supplier.get('env_prefix','ZAR_SUPPLIER')
        if not re.fullmatch(r'ZAR_SUPPLIER(?:_[A-Z0-9_]{1,50})?',prefix):raise ValueError('Prefijo de secretos proveedor inválido.')
        suffix={'catalog':'CATALOG_URL','quote':'QUOTE_URL','order':'ORDER_WEBHOOK','tracking':'TRACKING_URL'}[operation]
        return os.environ.get(prefix+'_'+suffix,'').strip(),os.environ.get(prefix+'_API_TOKEN','').strip()
    def call(self,operation,payload):
        url,token=self.configured(operation)
        if not url:raise ValueError('MANUAL_ACTION_REQUIRED: contrato '+operation+' del proveedor no configurado.')
        parsed=urlparse(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('El endpoint proveedor configurado debe ser HTTPS sin credenciales en URL.')
        headers={'Authorization':'Bearer '+token} if token else {}
        if payload.get('idempotency_key'):headers['Idempotency-Key']=payload['idempotency_key']
        fn=self.session.get if operation in {'catalog','tracking'} else self.session.post
        kw={'params':payload} if operation in {'catalog','tracking'} else {'json':payload}
        r=fn(url,headers=headers,timeout=(5,35),allow_redirects=False,**kw)
        if not r.ok:raise ValueError('Proveedor no confirmó '+operation+' (HTTP '+str(r.status_code)+').')
        result=r.json()
        if not isinstance(result,dict):raise ValueError('Contrato proveedor requiere objeto JSON.')
        return result
    def catalog(self,query):
        data=self.call('catalog',{'q':query})
        if not isinstance(data.get('products'),list):raise ValueError('Contrato catálogo requiere products[].')
        return data['products'][:100]
    def quote(self,payload):return self.call('quote',payload)
    def order(self,payload):return self.call('order',payload)
    def tracking(self,order_id):return self.call('tracking',{'order_id':order_id})
