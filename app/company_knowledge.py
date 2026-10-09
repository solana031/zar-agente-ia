"""Deterministic, source-preserving business knowledge; no inferred finances."""
import hashlib
import re


def rebuild(sources, previous=None):
    facts = []
    for source in sources:
        if not source.get('included') or not source.get('available'):
            continue
        text = source.get('excerpt') or ''
        # Only explicit labelled fields become facts. Summaries are not evidence.
        for line_number, line in enumerate(text.splitlines(), 1):
            match = re.fullmatch(r'\s*(Empresa|Cliente|Proveedor|NIF|CIF|Fecha|Total|Base imponible|IVA|Número de factura)\s*:\s*(.{1,300})\s*', line, re.I)
            if not match:
                continue
            kind, value = match.group(1).casefold(), match.group(2).strip()
            identity = hashlib.sha256((str(source['id']) + '\0' + kind + '\0' + value).encode()).hexdigest()[:24]
            if any(f['id'] == identity for f in facts):
                continue
            facts.append({'id': identity, 'type': kind, 'value': value,
                          'source_document': source['id'], 'source_name': source.get('name'),
                          'source_range': {'line': line_number}, 'source_page': None,
                          'date': source.get('updated_at') or source.get('created_at'),
                          'updated_at': source.get('updated_at') or source.get('created_at'),
                          'confidence': None, 'status': 'REVIEW_REQUIRED'})
    # Conflicting values remain visible; never silently choose a financial value.
    groups = {}
    for fact in facts:
        groups.setdefault((fact['source_document'], fact['type']), set()).add(fact['value'])
    for fact in facts:
        if len(groups[(fact['source_document'], fact['type'])]) > 1:
            fact['status'] = 'CONFLICT'
    old = {f['id']: f for f in (previous or {}).get('facts', [])}
    current = {f['id']: f for f in facts}
    return {'facts': facts, 'changes': {'added': len(current.keys() - old.keys()),
            'removed': len(old.keys() - current.keys()),
            'changed': sum(old[key] != current[key] for key in old.keys() & current.keys())},
            'method': 'EXPLICIT_LABELS', 'status': 'REVIEW_REQUIRED' if facts else 'NO_EXTRACTED_DATA'}
