from app.node_scheduling import choose_node


def test_cost_load_capabilities_offline_and_busy():
    def node(nid, cost, load=0, active=0, seen=90, caps=None):
        return {'id': nid, 'last_seen': seen, 'capabilities': caps or ['python'],
                'active_jobs': active, 'max_concurrency': 1,
                'cost': {'per_job': cost}, 'resources': {'cpu_count': 4, 'load': [load]}}
    cloud, one, two = node('cloud', .2), node('NODE-01', .1, seen=10), node('NODE-02', .05)
    assert choose_node([cloud, one, two], 'python', 100) == 'NODE-02'
    two['active_jobs'] = 1
    assert choose_node([cloud, one, two], 'python', 100) == 'cloud'
    assert choose_node([cloud, one, two], 'python', 100, .1) is None
    assert choose_node([cloud], 'browser', 100) is None
    assert choose_node([node('unknown', None)], 'python', 100, .1) is None
    assert choose_node([node('busy', 0, load=12)], 'python', 100) is None
