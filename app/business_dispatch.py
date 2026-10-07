"""Business domain dispatch; no trading imports, broker or Wallet transfer path."""
class CommerceOrchestrator:
    domain='commerce'
    tools={'commerce_review':'optimization','commerce_research':'research','commerce_pricing':'pricing',
           'commerce_listing':'listing','commerce_compare':'compare','commerce_score':'score'}
    @classmethod
    def execute(cls,scope,task):
        from . import commerce_workspace
        return commerce_workspace.operate(scope,cls.tools[task['tool']],task.get('payload',{}))

class AgencyOrchestrator:
    domain='web_agency'
    @staticmethod
    def execute(scope,task):
        from . import agency_crm
        if task['tool']=='agency_research':
            return agency_crm.operate(scope,'research',task.get('payload',{}))
        return {'leads':[{'id':x['id'],'state':x['state'],'next_action':x.get('next_action')}
                         for x in agency_crm.view(scope)['leads']], 'external_actions':False}

class SitesOrchestrator:
    domain='sites'
    @staticmethod
    def execute(scope,task):
        from . import site_projects
        if task['tool']=='site_build': return site_projects.build(scope,task['project_id'])
        if task['tool']=='site_analyze': return site_projects.analyze(scope,task['project_id'])
        raise ValueError('Herramienta Sites no autorizada.')

class MediaOrchestrator:
    domain='media'
    @staticmethod
    def execute(scope,task):
        from . import media_company
        # Existing worker owns project/checkpoint locks and all paid generation gates.
        return media_company.process_one(scope)

class BusinessOrchestrator:
    children={x.domain:x for x in (CommerceOrchestrator,AgencyOrchestrator,SitesOrchestrator,MediaOrchestrator)}
    @classmethod
    def execute(cls,domain,scope,task):
        if domain not in cls.children: raise ValueError('Dominio empresarial no autorizado.')
        return cls.children[domain].execute(scope,task)
