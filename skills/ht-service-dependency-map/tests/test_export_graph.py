import csv
import io
import unittest
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from export_graph import render, validate


def graph() -> dict[str, Any]:
    return dict(schema_version=1, root_id='a', root_scope='Product', run={},
                nodes=[dict(id=i, name=n) for i, n in [('c', 'C'), ('a', '=A'), ('b', 'B')]],
                sources=[dict(id='s', url='https://example.org/list', title='List', retrieved_at='2026-11-18', locator='Row 1')],
                edges=[{'from': a, 'to': b, 'relation': 'subprocessor', 'scope': 'Product', 'target_scope': 'Product', 'source_ids': ['s']}
                       for a, b in [('a', 'b'), ('a', 'c'), ('b', 'c'), ('b', 'a')]],
                coverage=[dict(node_id=i, scope='Product', status=status, **extra)
                          for i, status, extra in [('a', 'listed', {}), ('b', 'listed', {}),
                                                  ('c', 'not_expanded', {'reason': 'budget_limit'})]])


class ExportTests(unittest.TestCase):
    def test_shared_provider_scopes_do_not_join(self):
        data = graph()
        data['edges'].append({**data['edges'][0], 'target_scope': 'Other contract'})
        data['coverage'].append(dict(node_id='b', scope='Other contract', status='scope_unresolved'))
        diagram = render(data, ['mermaid'])['graph.mmd']
        self.assertIn('n0 --> n1', diagram)
        self.assertIn('n0 --> n2', diagram)
        self.assertIn('n2 --> n3', diagram)
        self.assertNotIn('n1 -->', diagram)
        data['coverage'].pop()
        with self.assertRaisesRegex(ValueError, 'Missing edge scope coverage'):
            validate(data)

    def test_multiple_outputs_preserve_graph(self):
        data = graph()
        files = render(data, ['json', 'csv', 'mermaid'])
        self.assertEqual(len(list(csv.DictReader(io.StringIO(files['edges.csv'])))), 4)
        self.assertIn("'=A", files['nodes.csv'])
        self.assertIn('"=A"', files['graph.json'])
        self.assertEqual(files['graph.mmd'].count('-->'), 4)
        data['nodes'].reverse()
        self.assertEqual(render(data, ['json', 'csv', 'mermaid']), files)

    def test_missing_or_invalid_reference(self):
        for references in [[], ['unknown'], 's', [[]]]:
            with self.subTest(references=references):
                data = graph()
                data['edges'][0]['source_ids'] = references
                with self.assertRaises(ValueError):
                    validate(data)

    def test_missing_coverage_and_duplicate_nodes(self):
        data = graph()
        data['coverage'].pop()
        with self.assertRaises(ValueError):
            validate(data)
        data = graph()
        data['nodes'].append(data['nodes'][0])
        with self.assertRaises(ValueError):
            validate(data)

    def test_diagram_limits_and_escapes(self):
        data = graph()
        data['nodes'][1]['name'] = 'A"\n%%{bad}%%'
        diagram = render(data, ['mermaid'], diagram_depth=0)['graph.mmd']
        self.assertIn('omitted', diagram)
        self.assertNotIn('%%{bad}%%', diagram)
        self.assertNotIn('-->', diagram)
