import os, tempfile
os.environ.setdefault('ZAR_DATA_DIR', tempfile.mkdtemp(prefix='zar-arch-test-'))

def test_subagent_router():
    from app.subagents import classify, tool_names_for
    assert classify('Busca mis últimos correos de Gmail').name == 'gmail'
    allowed, route = tool_names_for('Busca mis últimos correos de Gmail', {'gmail_search','gmail_recent','web_search','zar_get_context'})
    assert 'gmail_search' in allowed and 'web_search' not in allowed
    assert 'zar_get_context' in allowed

def test_context_graph_roundtrip():
    from app.context_graph import sync_runtime_context, relevant_context
    sync_runtime_context({'active_email': {'id':'m1','subject':'Factura restaurante','from':'a@example.com'}, 'focus': {'type':'email'}})
    text = relevant_context('factura restaurante')
    assert 'Factura restaurante' in text

def test_execution_bus_retries_read_only():
    from app.execution_bus import execute_with_policy
    calls={'n':0}
    def fake(name,args):
        calls['n'] += 1
        return {'ok': calls['n'] > 1, 'error':'temporary'}
    result=execute_with_policy('drive_search', {'query':'x'}, fake)
    assert result['ok'] is True and calls['n'] == 2
