"""Public Canva setup; no account, permission or design is fabricated."""
from . import holdings
from .identity_center import provider_plan,ensure

class CanvaAdapter:
    def status(self,scope):
        state=ensure(holdings.read(scope));plan=next((p for p in state['plans'] if p['service']=='CANVA'),None)
        return {'service':'CANVA','status':'HUMAN_ACTION_REQUIRED','identity':state['google'].get('email'),'url':'https://www.canva.com/signup/',
                'plan':plan,'designs_created_by_adapter':0,'message':'Conectar cuenta/OAuth y verificar permisos antes de crear diseños o exportar.','prepared_capabilities':['design_brief','presentations','social_assets','documents','branding','export']}
    def prepare(self,scope):
        provider_plan(scope,'CANVA');return self.status(scope)
