"""Business control plane in the existing, scoped Holdings store.

Only explicitly registered local tools execute here. Approval reserves funds;
it never sends money or pretends that a provider has accepted an operation.
"""
from copy import deepcopy
from decimal import Decimal
import secrets
import re
from . import holdings
from .business_connectors import inventory
from .business_dispatch import BusinessOrchestrator

TOOLS = {
    "RevenueAgent": ("business", "wallet_snapshot"),
    "OptimizationAgent": ("business", "profitability_review"),
    "AccountManagerAgent": ("identity", "account_inventory"),
    "ZARIdentityAgent": ("identity", "account_inventory"),
    "GoogleAccountAgent": ("identity", "account_inventory"),
    "AccountProvisioningAgent": ("identity", "provisioning_request"),
    "SiteResearchAgent": ("sites", "workflow_status"),
    "SiteBuilderAgent": ("sites", "workflow_status"),
    "ContentAgent": ("sites", "workflow_status"),
    "SEOAgent": ("sites", "workflow_status"),
    "AdSenseAgent": ("sites", "workflow_status"),
    "AnalyticsAgent": ("sites", "workflow_status"),
    "NicheResearchAgent": ("commerce","commerce_review"),
    "ProductScoutAgent": ("commerce","commerce_review"),
    "SupplierAgent": ("commerce","commerce_review"),
    "MarginAgent": ("commerce","commerce_review"),
    "PricingAgent": ("business","commerce_review"),
    "ListingAgent": ("commerce","commerce_review"),
    "OrderAgent": ("commerce","commerce_review"),
    "FulfillmentAgent": ("commerce","commerce_review"),
    "CustomerServiceAgent": ("commerce","commerce_review"),
    "LeadScoutAgent": ("web_agency","agency_review"),
    "BusinessResearchAgent": ("web_agency","agency_review"),
    "OpportunityScoreAgent": ("web_agency","agency_review"),
    "WebDesignerAgent": ("web_agency","agency_review"),
    "WebBuilderAgent": ("web_agency","agency_review"),
    "SalesOutreachAgent": ("web_agency","agency_review"),
    "NegotiationAgent": ("web_agency","agency_review"),
    "ClosingAgent": ("web_agency","agency_review"),
    "PaymentAgent": ("web_agency","agency_review"),
    "ProjectDeliveryAgent": ("web_agency","agency_review"),
}
ORCHESTRATORS = {'business':'BusinessOrchestrator','commerce':'CommerceOrchestrator',
                 'web_agency':'AgencyOrchestrator','sites':'SitesOrchestrator','media':'MediaOrchestrator'}
ACCOUNT_TYPES = {'EMAIL','GOOGLE','SHOPIFY','STRIPE','YOUTUBE','INSTAGRAM','TIKTOK','ADSENSE','VERCEL','SUPPLIER','DOMAIN','PHONE','BROKER','OTHER'}
MODES = {"OFF", "SHADOW", "SUPERVISED", "ACTIVE"}

def note_verified_account(d,provider,identity,secret_ref,verification_scope):
    """Only public account identity and the variable name; never token values."""
    o=ensure(d)
    row=next((x for x in o['accounts'] if x['provider']==provider and x['identity']==identity),None)
    if not row:
        row={'id':secrets.token_hex(12),'provider':provider,'identity':identity,'secret_ref':secret_ref,
            'expires_at':None,'human_step':None,'permissions':[]};o['accounts'].append(row)
    row.update(state='LISTO',verified_at=holdings._now(),updated_at=holdings._now(),verification_scope=verification_scope)
    return row


def register(app, scope_fn):
    from flask import jsonify, session, request

    @app.get('/api/holdings/orchestration')
    def business_orchestration_state_api():
        token = session.setdefault('business_csrf', secrets.token_urlsafe(32))
        return jsonify({'ok': True, 'csrf': token, **view(scope_fn())})

    @app.post('/api/holdings/orchestration/<action>')
    def business_orchestration_action_api(action):
        token = session.get('business_csrf')
        if not token or not secrets.compare_digest(token, request.headers.get('X-ZAR-Business-CSRF', '')):
            return jsonify({'ok': False, 'error': 'Protección CSRF: recarga Orquestación.'}), 403
        try:
            data = request.get_json(silent=True) or {}
            if not isinstance(data, dict):
                raise ValueError('Objeto JSON requerido.')
            return jsonify({'ok': True, **mutate(scope_fn(), action, data)})
        except (ValueError, KeyError, StopIteration, TypeError, ArithmeticError) as exc:
            return jsonify({'ok': False, 'error': str(exc) or 'Registro no encontrado.'}), 400


def ensure(d):
    d['account_identity_policy']={'operational_identity':'zaragente031@gmail.com','official_github_owner':'solana031@gmail.com','official_railway_owner':'solana031@gmail.com','migration_allowed':False}
    o = d.setdefault("orchestration", {})
    o['identity_policy']=deepcopy(d['account_identity_policy'])
    for key, value in {"mode": "OFF", "agents": {}, "tasks": [], "approvals": [],
                       "accounts": [], "decisions": [], "cycles": 0, "last_heartbeat": None}.items():
        o.setdefault(key, deepcopy(value))
    for name, (domain, tool) in TOOLS.items():
        o["agents"].setdefault(name, {
            "id": name, "name": name, "function": tool, "domain": domain,
            "state": "IDLE", "capabilities": [tool], "tools": [tool],
            "current_tasks": [], "completed_tasks": [], "errors": [],
            "last_heartbeat": None, "costs": None, "attributed_revenue": None,
            "logs": [], "permissions": ["local_read"], "dependencies": [],
        })
    for name in ['SemanticPlanner','ResearchAgent','SourceVerifier','ReportAgent','DocumentAgent','SpreadsheetAgent','PresentationAgent','ArtifactOrchestrator','ContactResolver','MailAgent','CanvaAdapter']:
        parent='IDENTITY' if name in {'ContactResolver','MailAgent','CanvaAdapter'} else 'BusinessOrchestrator' if name in {'SemanticPlanner','ArtifactOrchestrator','ResearchAgent'} else 'ArtifactOrchestrator'
        o['agents'].setdefault(name,{'id':name,'name':name,'domain':'identity' if parent=='IDENTITY' else 'business','parent':parent,'function':'semantic_tasks_status','state':'AVAILABLE' if name!='CanvaAdapter' else 'HUMAN_ACTION_REQUIRED','tools':['semantic_tasks_status'],'capabilities':['structured_tasks' if name=='SemanticPlanner' else 'artifact_pipeline'],'current_tasks':[],'errors':[],'permissions':['local_read']})
    for name, tool in [('AccountProvisioningAgent','provisioning_request'),('SiteBuilderAgent','site_build'),('SEOAgent','site_analyze'),
                       ('OptimizationAgent','project_review'),('AnalyticsAgent','project_review'),('ContentAgent','project_review')]:
        a=o['agents'][name]
        if tool not in a['tools']: a['tools'].append(tool);a['capabilities'].append(tool)
    for name,tool in [('OptimizationAgent','commerce_review'),('NicheResearchAgent','commerce_research'),
                      ('PricingAgent','commerce_pricing'),('MarginAgent','commerce_pricing'),('ListingAgent','commerce_listing'),
                      ('SupplierAgent','commerce_compare'),('ProductScoutAgent','commerce_score'),
                      ('BusinessResearchAgent','agency_research'),('QAAgent','agency_review')]:
        if name not in o['agents']:
            o['agents'][name]={'id':name,'name':name,'function':tool,'domain':'web_agency','state':'IDLE',
                'tools':[],'capabilities':[],'current_tasks':[],'completed_tasks':[],'errors':[],'logs':[],
                'last_heartbeat':None,'costs':None,'attributed_revenue':None,'permissions':['local_read'],'dependencies':[]}
        a=o['agents'][name]
        if tool not in a['tools']:a['tools'].append(tool);a['capabilities'].append(tool)
    return o


def money(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Importe positivo con un máximo de dos decimales requerido.")
    return amount


def wallet(d):
    """Book balances by currency; never confuse book cash with bank balances."""
    currencies = {}
    for row in d.get("ledger", []):
        currency = row.get("currency", "EUR")
        b = currencies.setdefault(currency, {k: Decimal(0) for k in
            ("manual_funding", "revenue", "expenses", "pending_income", "pending_payments", "committed")})
        amount = Decimal(str(row["amount"]))
        if not amount.is_finite() or amount < 0:
            raise ValueError("Ledger histórico inválido; revisar antes de operar.")
        kind, status = row.get("kind"), row.get("status")
        if status == "collected":
            key = {"deposit": "manual_funding", "revenue": "revenue", "cost": "expenses", "expense": "expenses"}.get(kind)
        elif status == "pending":
            key = "pending_income" if kind == "revenue" else "pending_payments" if kind in {"cost", "expense"} else None
        else:
            key = None
        if key:
            b[key] += amount
    for approval in ensure(d)["approvals"]:
        if approval["state"] == "APPROVED":
            b = currencies.setdefault(approval["currency"], {k: Decimal(0) for k in
                ("manual_funding", "revenue", "expenses", "pending_income", "pending_payments", "committed")})
            b["committed"] += Decimal(approval["total"])
    for b in currencies.values():
        b["profit"] = b["revenue"] - b["expenses"]
        b["available"] = b["manual_funding"] + b["profit"] - b["committed"] - b["pending_payments"]
    from .trading_capital import assigned
    if d.get('trading_capital'):
        b=currencies.setdefault('USD',{k:Decimal(0) for k in ('manual_funding','revenue','expenses','pending_income','pending_payments','committed','profit','available')})
        b['trading_reserved']=assigned(d)
        b['available']-=b['trading_reserved']
    return {"state": "REGISTRO LOCAL" if currencies else "NO CONECTADO",
            "bank_state": "NO CONECTADO", "balances": {c: {k: str(v) for k, v in b.items()} for c, b in currencies.items()},
            "note": "Saldos contables declarados/importados; no verifican saldo bancario. Sin conversión entre monedas."}


def view(scope):
    from .financial_events import sync_existing, summary
    from .financial_provider import FinancialProvider
    sync_existing(scope)
    with holdings.transaction(scope):
        state=holdings.read(scope)
        from .identity_center import ensure as identity, queue
        center=identity(state)
        if not any(a.get('service')=='FINANCIAL_PROVIDER' and a.get('status')!='DONE' for a in center['human_actions']):
            proof=FinancialProvider().capabilities()
            action=queue(center,'FINANCIAL_PROVIDER',proof['human_action'],proof['next_step'],'',['Elegir proveedor de tesorería.','Completar personalmente identidad/KYC, banco y términos en el portal oficial.','Configurar credenciales solo en servidor y verificar capacidad de ejecución antes de habilitar pagos.'])
            action.update(group='PAYMENTS',account='zaragente031@gmail.com')
            holdings.write(scope,state)
    d = holdings.read(scope)
    o = ensure(d)
    return {**deepcopy(o), "orchestrators": {name:{"domain":domain,"agents":[a["id"] for a in o["agents"].values() if a.get("domain")==domain],"trading_authority":False} for domain,name in ORCHESTRATORS.items()}, "wallet": wallet(d), "global_stop": d.get("global_stop", False),
            "connectors": inventory(d),
            "ledger": d.get("ledger", [])[-100:][::-1], "budgets":d.get("treasury_budgets",{}),
            "financial_events":summary(d), "financial_provider":FinancialProvider().capabilities()}


def mutate(scope, action, data):
    with holdings.transaction(scope):
        d = holdings.read(scope)
        o = ensure(d)
        now = holdings._now()
        if action == "budget":
            business=str(data.get("business",""))
            if business not in {"sites","reselling","clipper","agency","infrastructure","marketing"}:raise ValueError("Negocio no permitido.")
            currency=str(data.get("currency","EUR")).upper()
            if currency not in {"EUR","USD","GBP"}:raise ValueError("Moneda no permitida.")
            limits={key:Decimal(str(data.get(key))) for key in ("assigned","max_action","max_day","max_month")}
            if any(not x.is_finite() or x<0 or x!=x.quantize(Decimal("0.01")) for x in limits.values()):raise ValueError("Límites no negativos con dos decimales requeridos.")
            limits={key:str(value) for key,value in limits.items()}
            d.setdefault("treasury_budgets",{})[business]={**limits,"currency":currency,"updated_at":now,"external_spending":"CONFIRM","note":"Límites declarados; no aportan fondos ni habilitan pagos."}
        elif action == "deposit":
            amount = money(data.get("amount"))
            reference = str(data.get("reference", "")).strip()[:100]
            if not reference:
                raise ValueError("Referencia requerida para evitar duplicados.")
            holdings.add_ledger(scope, "zar", "deposit", float(amount), currency=data.get("currency", "EUR"),
                reference="funding:" + reference, source="pablo_manual", note="Aportación declarada; no verifica ingreso bancario.")
            d = holdings.read(scope)
            o = ensure(d)
        elif action == "account":
            allowed = {"id", "provider", "identity", "secret_ref", "expires_at", "human_step", "type", "account_id", "display_name", "oauth_state"}
            if set(data) - allowed:
                raise ValueError("Solo metadatos y referencias a secretos; no enviar credenciales.")
            account_type = str(data.get('type') or 'OTHER').upper()
            if account_type not in ACCOUNT_TYPES: raise ValueError('Tipo de cuenta no permitido.')
            provider = str(data.get("provider", "")).strip()
            identity = str(data.get("identity", "")).strip()
            if provider.upper() in {'GITHUB', 'RAILWAY'} and identity.lower() != 'solana031@gmail.com':
                raise ValueError('GitHub y Railway oficiales conservan la identidad de Pablo: solana031@gmail.com.')
            ref = str(data.get("secret_ref", "")).strip()
            if not provider or not identity or (ref and not re.fullmatch(r"[A-Z][A-Z0-9_]{2,80}", ref)):
                raise ValueError("Proveedor, identidad y nombre de variable seguro requeridos.")
            human_step = data.get("human_step") or None
            if human_step not in {None, "CAPTCHA", "SMS", "KYC", "TERMS", "HUMAN_VERIFICATION"}:
                raise ValueError("Intervención no válida.")
            previous = next((a for a in o["accounts"] if a["provider"] == provider and a["identity"] == identity), None)
            if not previous and len(o["accounts"]) >= 100:
                raise ValueError("Límite de cuentas alcanzado.")
            row = {"id": previous["id"] if previous else secrets.token_hex(12), "provider": provider[:100],
                "identity": identity[:200], "secret_ref": ref or None, "expires_at": data.get("expires_at") or None,
                "human_step": human_step, "state": "AWAITING_HUMAN" if human_step else "POR CONFIGURAR",
                "permissions": [], "updated_at": now, "verified_at": None,
                "type":account_type,"account_id":str(data.get('account_id') or identity)[:200],
                "display_name":str(data.get('display_name') or identity)[:200],
                "oauth_state":'UNVERIFIED',"last_verified":None,"status":"POR CONFIGURAR","secret_reference":ref or None}
            if previous:
                previous.update(row)
            else:
                o["accounts"].append(row)
        elif action == "mode":
            mode = data.get("mode")
            if mode not in MODES:
                raise ValueError("Modo inválido.")
            if d.get("global_stop") and mode != "OFF":
                raise ValueError("STOP GLOBAL activo.")
            o["mode"] = mode
        elif action == "agent":
            a = o["agents"][data["id"]]
            if data.get("state") not in {"IDLE", "PAUSED", "OFF"}:
                raise ValueError("Estado inválido.")
            a["state"] = data["state"]
        elif action == "task":
            a = o["agents"][data["agent"]]
            tool = data.get("tool")
            if tool not in a["tools"]:
                raise ValueError("Herramienta no autorizada.")
            if len(o["tasks"]) >= 1000:
                raise ValueError("Límite de tareas alcanzado.")
            deps = list(dict.fromkeys(data.get("dependencies", [])))
            if any(dep not in {t["id"] for t in o["tasks"]} for dep in deps):
                raise ValueError("Dependencia inexistente.")
            key = str(data.get("request_id") or "")[:100]
            previous = next((t for t in o["tasks"] if key and t["request_id"] == key), None)
            if not previous:
                project_id=data.get('project_id')
                if tool in {'site_build','site_analyze'}:
                    from . import site_projects
                    site_projects.get(scope,project_id)
                o["tasks"].append({"id": secrets.token_hex(12), "agent": a["id"], "tool": tool,
                    "project_id":project_id,
                    "payload":data.get('payload',{}) if isinstance(data.get('payload',{}),dict) else {},
                    "state": "QUEUED", "dependencies": deps, "request_id": key,
                    "created_at": now, "updated_at": now, "attempts": 0, "result": None, "error": None})
        elif action == "retry":
            t = next(t for t in o["tasks"] if t["id"] == data["id"])
            if t["state"] != "ERROR" or t["attempts"] >= 3:
                raise ValueError("Solo se reintentan errores, máximo tres intentos.")
            t.update(state="QUEUED", updated_at=now, error=None)
        elif action == "prepare":
            if len(o["approvals"]) >= 1000:
                raise ValueError("Límite de propuestas alcanzado.")
            currency = str(data.get("currency", "EUR")).upper()
            if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
                raise ValueError("Moneda inválida.")
            price = money(data.get("price"))
            tax = None if data.get("tax") is None else Decimal(str(data["tax"]))
            if tax is not None and (not tax.is_finite() or tax < 0 or tax != tax.quantize(Decimal("0.01"))):
                raise ValueError("Impuestos inválidos.")
            total = price + (tax or Decimal(0))
            item, provider = str(data.get("item", "")).strip(), str(data.get("provider", "")).strip()
            if not item or not provider:
                raise ValueError("Indica qué se compra y proveedor.")
            o["approvals"].append({"id": secrets.token_hex(12), "item": item[:300], "provider": provider[:150],
                "price": str(price), "tax": None if tax is None else str(tax), "total": str(total),
                "currency": currency, "state": "PENDING", "created_at": now,
                "business":str(data.get("business","")), "execution_state": "NO DISPONIBLE", "note": "Propuesta local. Falta checkout verificable; aprobación solo reserva fondos."})
        elif action in {"approve", "reject", "cancel"}:
            p = next(p for p in o["approvals"] if p["id"] == data["id"])
            if action == "approve":
                if p.get('quote_id'):
                    from datetime import datetime,timezone
                    if datetime.fromisoformat(p['expires_at'])<=datetime.now(timezone.utc):raise ValueError('Quote proveedor caducado; no reservar ni aprobar.')
                if d.get("global_stop") or o["mode"] in {"OFF", "SHADOW"}:
                    raise ValueError("Aprobación bloqueada por modo/STOP GLOBAL.")
                if p["state"] != "PENDING" or data.get("confirmed") is not True or str(data.get("total")) != p["total"]:
                    raise ValueError("Confirmación explícita del total requerido.")
                budgets=d.get('treasury_budgets',{})
                if budgets:
                    business=p.get('business');budget=budgets.get(business)
                    if not budget:raise ValueError('Selecciona un negocio con presupuesto antes de aprobar.')
                    if budget['currency']!=p['currency']:raise ValueError('Moneda distinta al presupuesto; no se convierte automáticamente.')
                    total=Decimal(p['total'])
                    approved=[x for x in o['approvals'] if x.get('business')==business and x.get('state') in {'APPROVED','EXECUTED'}]
                    day=now[:10];month=now[:7]
                    def committed(prefix):return sum((Decimal(x['total']) for x in approved if str(x.get('updated_at') or x.get('created_at','')).startswith(prefix)),Decimal(0))
                    if total>Decimal(budget['max_action']) or committed(day)+total>Decimal(budget['max_day']) or committed(month)+total>Decimal(budget['max_month']) or committed('')+total>Decimal(budget['assigned']):raise ValueError('La solicitud excede los límites o presupuesto del negocio.')
                before = Decimal(wallet(d)["balances"].get(p["currency"], {}).get("available", "0"))
                if before < Decimal(p["total"]):
                    raise ValueError("Saldo contable insuficiente.")
                p.update(state="APPROVED", balance_before=str(before), balance_after=str(before-Decimal(p["total"])))
            else:
                if p.get('execution_state') in {'REQUESTED','REVIEW_REQUIRED','ORDERED','ORDERED_AWAITING_RECEIPT','CHARGED'}:
                    raise ValueError('Pedido enviado/ambiguo: no liberar reserva sin reconciliación del proveedor.')
                if p["state"] not in {"PENDING", "APPROVED"}:
                    raise ValueError("Propuesta ya cerrada.")
                p["state"] = "REJECTED" if action == "reject" else "CANCELLED"
            p["updated_at"] = now
        else:
            raise ValueError("Acción no soportada.")
        o["decisions"].append({"timestamp": now, "action": action, "mode": o["mode"], "execution_authority": False})
        o["decisions"] = o["decisions"][-500:]
        holdings.write(scope, d)
        if action == 'prepare':
            from .jev_decision import evaluate
            proposal=o['approvals'][-1]
            gate=evaluate(scope,{'action':'PAYMENT','agent':'Treasury','task_id':proposal['id'],'cost':proposal['total']})
            updated=holdings.read(scope)
            updated['orchestration']['approvals'][-1]['jev_decision']=gate
            holdings.write(scope,updated)
    return view(scope)


def tick(scope):
    # Local handlers are bounded and execute under the same state transaction.
    with holdings.transaction(scope):
        d = holdings.read(scope)
        o = ensure(d)
        if d.get("global_stop") or o["mode"] == "OFF":
            return
        now = holdings._now()
        o["cycles"] += 1
        o["last_heartbeat"] = now
        for t in o["tasks"]:
            a = o["agents"][t["agent"]]
            if t["state"] != "QUEUED" or a["state"] in {"OFF", "PAUSED"}:
                continue
            if any(next(x for x in o["tasks"] if x["id"] == dep)["state"] != "DONE" for dep in t["dependencies"]):
                continue
            if o["mode"] == "SHADOW":
                t.update(result={"simulation": True, "planned_tool": t["tool"]}, updated_at=now)
                continue
            t["attempts"] += 1
            try:
                from . import jev_decision
                gate=jev_decision.proposal(scope,{'source_agent':a['id'],'task':t['tool'],'task_id':t['id'],
                    'action':'Execute local '+t['tool'],'resources':['local_write'] if t['tool'] in {'site_build','site_analyze'} else ['local_read'],
                    'expected_cost':0,'expected_revenue':None,'risk':.1,'urgency':.5})
                # Merge the appended decision before our transaction commits its state.
                d['jev_decisions']=holdings.read(scope).get('jev_decisions',[])
                t['jev_decision_id']=gate['id']
                if gate['decision']!='APPROVE':
                    t.update(state='DEFERRED',error=gate['output']['reasoning'])
                    holdings.write(scope,d)
                    break
                if t["tool"] == "wallet_snapshot":
                    result = wallet(d)
                elif t["tool"] == "account_inventory":
                    result = {"accounts": o["accounts"], "state": "POR CONFIGURAR" if not o["accounts"] else "INVENTARIO LOCAL"}
                elif t['tool']=='provisioning_request':
                    from .identity_center import natural_request
                    result=natural_request(scope,t.get('payload',{}).get('request'))
                    fresh=holdings.read(scope);d['identity_center']=fresh['identity_center']
                    for aid,agent in fresh['orchestration']['agents'].items():
                        if aid not in o['agents']:o['agents'][aid]=agent
                elif t["tool"] == "profitability_review":
                    balances = wallet(d)["balances"]
                    reviews = {}
                    for currency, balance in balances.items():
                        expense, profit = Decimal(balance["expenses"]), Decimal(balance["profit"])
                        reviews[currency] = {"roi": str(profit / expense) if expense else None,
                            "loss_detected": profit < 0,
                            "next_action": "Revisar y pausar procesos con pérdidas antes de asumir nuevos costes" if profit < 0
                                else "Validar atribución y cobros antes de escalar"}
                    result = {"currencies": balances, "reviews": reviews, "external_actions": False,
                              "source": "ledger_local", "bank_verified": False}
                elif t['tool'] in {'commerce_review','commerce_research','commerce_pricing','commerce_listing','commerce_compare','commerce_score'}:
                    from . import commerce_workspace
                    result=BusinessOrchestrator.execute('commerce',scope,t)
                    fresh=holdings.read(scope);d['commerce_workspace']=fresh['commerce_workspace'];d['companies']=fresh['companies']
                elif t['tool'] in {'agency_review','agency_research'}:
                    from . import agency_crm
                    result=BusinessOrchestrator.execute('web_agency',scope,t)
                    d['agency_crm']=holdings.read(scope)['agency_crm']
                elif t['tool']=='workflow_status':
                    result={'companies':{k:{'state':c['state'],'cycles':c['cycles'],'last_error':c['last_error']} for k,c in d['companies'].items()},
                        'adsense':d.get('adsense'), 'note':'Estado persistido; no activa proveedores.'}
                elif t['tool']=='project_review':
                    from . import sites_company
                    projects=[]
                    for project in sites_company._read_registry(scope):
                        metrics=project.get('metrics') or {}
                        earnings=metrics.get('ESTIMATED_EARNINGS')
                        low=None if earnings is None else Decimal(str(earnings))<=0
                        steps=list((project.get('seo') or {}).get('next_steps',[]))
                        if project.get('content_review_required'):steps.append('Revisar contenido y fuentes antes de publicar')
                        if low is True:steps.append('Revisar cobertura, contenido e informe AdSense; no fabricar tráfico')
                        projects.append({'project_id':project['id'],'state':project.get('state'),
                            'low_performance':low,'metrics_source':'Google AdSense API' if metrics else None,
                            'recommendations':steps,'generated_content':None})
                    result={'projects':projects,'source':'persisted_projects','external_actions':False,
                        'note':'Revisión local; rendimiento desconocido sin métricas por sitio. No genera contenido con un proveedor sin aprobación.'}
                elif t['tool'] in {'site_build','site_analyze'}:
                    from . import site_projects
                    result=BusinessOrchestrator.execute('sites',scope,t)
                    d['companies']=holdings.read(scope)['companies']
                else:
                    raise ValueError("No existe ejecutor autorizado.")
                t.update(state="DONE", result=result, error=None)
                a["completed_tasks"].append(t["id"])
                for decision in d.get('jev_decisions',[]):
                    if decision['id']==gate['id']:decision['subsequent_state']='DONE'
            except Exception as exc:
                t.update(state="ERROR", error=type(exc).__name__)
                a["errors"].append({"task": t["id"], "error": t["error"], "timestamp": now})
            t["updated_at"] = now
            a["last_heartbeat"] = now
            a["logs"].append({"task": t["id"], "state": t["state"], "timestamp": now})
            a["logs"] = a["logs"][-100:]
            o["decisions"].append({"timestamp": now, "action": "TASK_RESULT", "task": t["id"],
                "tool": t["tool"], "state": t["state"], "mode": o["mode"], "execution_authority": False})
            o["decisions"] = o["decisions"][-500:]
            break
        for a in o["agents"].values():
            a["current_tasks"] = [t["id"] for t in o["tasks"] if t["agent"] == a["id"] and t["state"] == "QUEUED"]
        holdings.write(scope, d)
