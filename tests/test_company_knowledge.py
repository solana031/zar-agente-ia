import unittest
from app.company_knowledge import rebuild


class CompanyKnowledgeTest(unittest.TestCase):
    def source(self, text, **kwargs):
        return dict(id='invoice', name='Factura.txt', included=True,
                    available=True, excerpt=text, updated_at='2026-10-09', **kwargs)

    def test_only_explicit_fields_and_provenance(self):
        result = rebuild([self.source('Estimación total 999\nTotal: 12 EUR\nTotal: 12 EUR\nCliente: ZAR')])
        self.assertEqual(len(result['facts']), 2)
        self.assertEqual(result['facts'][0]['source_range'], {'line': 2})
        self.assertIsNone(result['facts'][0]['confidence'])
        self.assertEqual(result['facts'][0]['source_document'], 'invoice')

    def test_conflicts_preserved_and_incremental_changes(self):
        old = rebuild([self.source('Total: 12 EUR')])
        new = rebuild([self.source('Total: 12 EUR\nTotal: 15 EUR')], old)
        self.assertEqual(new['changes']['added'], 1)
        self.assertEqual({f['status'] for f in new['facts']}, {'CONFLICT'})
        self.assertEqual(rebuild([self.source('Total: 12 EUR\nTotal: 15 EUR')], new)['changes'],
                         {'added': 0, 'removed': 0, 'changed': 0})

    def test_excluded_or_removed_sources_are_not_current_facts(self):
        source = self.source('Total: 12 EUR')
        old = rebuild([source])
        source['included'] = False
        self.assertEqual(rebuild([source], old)['changes']['removed'], 1)
        self.assertEqual(source['excerpt'], 'Total: 12 EUR')


if __name__ == '__main__':
    unittest.main()
