import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'ht_inventory.py'
spec = importlib.util.spec_from_file_location('inventory', SCRIPT)
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def connection(nodes, total=None, cursor=None):
    return {'nodes': nodes, 'totalCount': len(nodes) if total is None else total,
            'pageInfo': {'hasNextPage': cursor is not None, 'endCursor': cursor}}


class InventoryTests(unittest.TestCase):
    def test_urls(self):
        self.assertEqual(m.parse_scope('https://github.com/orgs/example/repositories/'),
                         ('organization', 'example'))
        self.assertEqual(m.parse_scope('https://github.com/enterprises/example/organizations'),
                         ('enterprise', 'example'))
        for url in ['http://github.com/orgs/a/repositories',
                    'https://user:password@github.com/orgs/a/repositories',
                    'https://github.com/orgs/a/repositories?q=x',
                    'https://github.com/orgs/a/repositories#x',
                    'https://other.test/orgs/a/repositories',
                    'https://github.com/orgs/a%2Fb/repositories']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                m.parse_scope(url)

    def test_pagination(self):
        pages = iter([connection([{'id': '1'}], 2, 'next'),
                      connection([{'id': '2'}], 2)])
        cursors = []
        def fetch(cursor):
            cursors.append(cursor)
            return next(pages)
        self.assertEqual(len(m.collect(fetch)), 2)
        self.assertEqual(cursors, [None, 'next'])

    def test_inconsistent_connections(self):
        cases = [
            [connection([{'id': '1'}], 2)],
            [connection([{'id': '1'}, {'id': '1'}], 2)],
            [connection([{'id': '1'}], 2, 'x'), connection([{'id': '2'}], 3)],
            [connection([{'id': '1'}], 3, 'x'), connection([{'id': '2'}], 3, 'x')],
            [connection([None], 1)],
        ]
        for pages in cases:
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                iterator = iter(pages)
                m.collect(lambda cursor: next(iterator))

    def test_enterprise_includes_empty_org_and_all_repo_flags(self):
        calls = []
        def api(query, variables):
            calls.append(variables)
            if 'enterprise' in query:
                return {'enterprise': {'organizations': connection([
                    {'id': 'o1', 'login': 'empty'}, {'id': 'o2', 'login': 'full'}])}}
            repos = [] if variables['login'] == 'empty' else [
                {'id': 'r1', 'nameWithOwner': 'full/archived', 'isArchived': True,
                 'isFork': True, 'hasIssuesEnabled': False}]
            return {'organization': {'repositories': connection(repos)}}
        result = m.inventory('enterprise', 'example', api)
        self.assertEqual(len(result['organizations']), 2)
        self.assertEqual(result['organizations'][0]['repositories'], [])
        self.assertEqual(result['repository_count'], 1)
        self.assertTrue(result['pagination_complete'])
        self.assertFalse(result['administrative_coverage_verified'])
        self.assertEqual(len(calls), 3)

    def test_graphql_partial_errors_fail(self):
        with self.assertRaises(ValueError):
            m.unwrap({'data': {'enterprise': {}}, 'errors': [{'message': 'denied'}]})
        with self.assertRaises(ValueError):
            m.unwrap({'data': None})

    def test_missing_scope_fails(self):
        with self.assertRaises(ValueError):
            m.inventory('organization', 'example', lambda q, v: {'organization': None})


if __name__ == '__main__':
    unittest.main()
