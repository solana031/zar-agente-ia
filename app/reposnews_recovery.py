"""Bounded recovery of the frozen failed cohort; no publication authority."""
import time
from . import holdings,reposnews as rn


def classify(row):
    error=str(row.get('error') or '');detail=row.get('error_diagnostic') or {}
    mapping=[('AUTH_FAILED',('AUTH','TOKEN','401')),('PROVIDER_RATE_LIMIT',('RATE_LIMIT','429')),
             ('DELETED_SOURCE',('HTTP_410','DELETED')),('INVALID_REEL',('INVALID_REEL',)),
             ('DOWNLOAD_FAILED',('DOWNLOAD',)),('TRANSCRIPT_FAILED',('TRANSCRIPT','ASR')),
             ('OCR_FAILED',('OCR_FAILED',)),('MEDIA_UNAVAILABLE',('UNAVAILABLE','HTTP_404'))]
    kind=next((kind for kind,words in mapping if any(w in error for w in words)),'UNKNOWN')
    partial=bool(row.get('analysis') or row.get('public_metadata') or row.get('source_url'))
    # Source-validation errors are not proof that the Reel has been deleted.
    permanent=kind in {'DELETED_SOURCE','INVALID_REEL'} or kind=='MEDIA_UNAVAILABLE' and not partial
    return {'classification':kind,'retryable':not permanent,'permanent':permanent,'original_code':error,
            'partial_evidence':partial,'stage':detail.get('component'),'classified_at':holdings._now()}


def tick():
    with holdings.transaction('reposnews-editorial'):
        data=rn.read();job=data.get('reel_recovery_118',{})
        if not job or job.get('failure_lease_until',0)>time.time():return
        done=job.setdefault('failure_completed',[])
        item=next((i for i in job.get('failed_ids',[]) if i not in done),None)
        if not item:return
        row=next((r for r in data.get('instagram_inbox',[]) if r['id']==item),None)
        if not row:done.append(item);rn.write(data);return
        job['failure_lease_until']=time.time()+600;rn.write(data);snapshot=dict(row)
    result=classify(snapshot);identification=None
    if result['retryable'] and result['original_code']!='UNVERIFIED_COMMAND':
        from .reposnews_identification import identify
        try:identification=identify(data,snapshot)
        except (ValueError,OSError):result['research_error']='OFFICIAL_VERIFICATION_PENDING'
    with holdings.transaction('reposnews-editorial'):
        data=rn.read();job=data['reel_recovery_118'];row=next(r for r in data['instagram_inbox'] if r['id']==item)
        row['failure_recovery']=result;row.setdefault('error_history',[]).append(dict(row.get('error_diagnostic') or {},code=result['original_code']))
        job['failure_completed'].append(item);job['failure_lease_until']=0
        if result['permanent']:row.update(status='FAILED_PERMANENT',retry_after=0)
        elif result['original_code']=='UNVERIFIED_COMMAND' and row.get('research_package'):
            row.update(status='FAILED_RETRYABLE',retry_after=max(row.get('retry_after',0),time.time()+60),run_attempts=0,
                       attempt_limit=row.get('attempts',0)+2,
                       modification_request='Recuperar el borrador con fuentes verificadas. Omitir comandos y bloques de código que no consten literalmente en el README. No cambiar hechos ni publicar.')
        elif identification and identification.get('status')=='AUTO_IDENTIFIED':
            proof=identification['resolution'];row['expanded_identification']=identification
            row.update(automatic_project=proof['name'],automatic_repo=proof.get('repo'),status='FAILED_RETRYABLE',
                       retry_after=max(row.get('retry_after',0),time.time()+60),run_attempts=0,attempt_limit=row.get('attempts',0)+2)
            row.setdefault('analysis',{})['official_entity_sources']=proof.get('sources',[])
        else:
            row['failure_recovery']['outcome']='PARTIAL_EVIDENCE_REQUIRES_REVIEW'
            if identification:row['failure_recovery']['candidates']=identification.get('candidates',[])
        rn.write(data)
