"""Validate and export a public subprocessor research snapshot (no network)."""
import argparse
from collections import defaultdict, deque
import csv
import io
import json
from pathlib import Path
from urllib.parse import urlsplit

FIELDS = {
    'nodes': ('id', 'name', 'kind', 'official_url'),
    'edges': ('from', 'to', 'relation', 'scope', 'target_scope', 'purpose'),
    'sources': ('id', 'url', 'title', 'retrieved_at', 'locator', 'updated_at'),
    'coverage': ('node_id', 'scope', 'status', 'reason'),
}
FORMATS = ('json', 'csv', 'mermaid')
STATUSES = {'listed', 'explicitly_none', 'not_found', 'access_unavailable',
            'scope_unresolved', 'not_expanded'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def validate(graph):
    require(isinstance(graph, dict) and type(graph.get('schema_version')) is int
            and graph['schema_version'] == 1 and isinstance(graph.get('run'), dict),
            'Expected schema_version 1 and a run object')
    required = {'nodes': ('id', 'name'), 'edges': FIELDS['edges'][:-1],
                'sources': FIELDS['sources'][:-1], 'coverage': FIELDS['coverage'][:-1]}
    for table, keys in required.items():
        rows = graph.get(table)
        if not isinstance(rows, list):
            raise ValueError(f'{table} must be a list')
        for row in rows:
            require(isinstance(row, dict) and all(text(row.get(k)) for k in keys),
                    f'{table} requires nonempty strings: {", ".join(keys)}')
            require(all(text(row[k]) for k in FIELDS[table] if k in row),
                    f'{table} fields must be nonempty strings')
    ids = {}
    for table in ('nodes', 'sources'):
        ids[table] = {row['id'] for row in graph[table]}
        require(len(ids[table]) == len(graph[table]), f'Duplicate {table} ID')
    require(text(graph.get('root_id')) and graph['root_id'] in ids['nodes'], 'Unknown root ID')
    require(text(graph.get('root_scope')), 'Missing root scope')
    for row in graph['sources']:
        url = urlsplit(row['url'])
        require(url.scheme in ('http', 'https') and url.hostname and not url.username,
                'Expected a public source URL without credentials')
    edge_keys = set()
    for edge in graph['edges']:
        key = tuple(edge[k] for k in FIELDS['edges'][:-1])
        require(key not in edge_keys, 'Duplicate edge; combine its source IDs')
        edge_keys.add(key)
        require(edge['from'] in ids['nodes'] and edge['to'] in ids['nodes'], 'Unknown edge endpoint')
        require(edge['relation'] == 'subprocessor', 'Unsupported relation')
        refs = edge.get('source_ids')
        require(isinstance(refs, list) and refs and all(text(r) and r in ids['sources'] for r in refs)
                and len(set(refs)) == len(refs), 'Each edge needs distinct, existing source IDs')
    coverage_keys = set()
    for row in graph['coverage']:
        key = (row['node_id'], row['scope'])
        require(row['node_id'] in ids['nodes'] and key not in coverage_keys, 'Invalid coverage target')
        coverage_keys.add(key)
        require(row['status'] in STATUSES, 'Unknown coverage status')
        if row['status'] == 'not_expanded':
            require(row.get('reason') in ('depth_limit', 'budget_limit'), 'Missing expansion limit reason')
    require({node for node, _ in coverage_keys} == ids['nodes'], 'Missing node coverage')
    require((graph['root_id'], graph['root_scope']) in coverage_keys, 'Missing root scope coverage')
    for edge in graph['edges']:
        require((edge['from'], edge['scope']) in coverage_keys
                and (edge['to'], edge['target_scope']) in coverage_keys, 'Missing edge scope coverage')


def csv_table(columns, rows):
    def safe(value):
        if value.startswith(('\t', '\r', '\n')) or value.lstrip().startswith(
            ('=', '+', '-', '@', '＝', '＋', '－', '＠')
        ):
            return "'" + value
        return value

    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows([safe(row.get(k, '')) for k in columns] for row in rows)
    return buffer.getvalue()


def mermaid(graph, limit):
    adjacency = defaultdict(list)
    for edge in graph['edges']:
        adjacency[edge['from'], edge['scope']].append((edge['to'], edge['target_scope']))
    root = (graph['root_id'], graph['root_scope'])
    depth = {root: 0}
    queue = deque([root])
    while queue:
        node = queue.popleft()
        if depth[node] < limit:
            for child in adjacency[node]:
                if child not in depth:
                    depth[child] = depth[node] + 1
                    queue.append(child)
    labels = {node: f'n{i}' for i, node in enumerate(sorted(depth))}
    lines = ['flowchart LR']
    names = {node['id']: node['name'] for node in graph['nodes']}
    for (node, scope), label in labels.items():
        name = ' '.join(f'{names[node]} ({scope})'.split())
        name = ''.join(c if c.isalnum() or c in ' ._-' else f'#{ord(c)};' for c in name)
        lines.append(f'  {label}["{name}"]')
    edges = [(labels[a], labels[b]) for a, children in adjacency.items()
             for b in children if a in labels and b in labels]
    lines.extend(f'  {a} --> {b}' for a, b in edges)
    missing_nodes = len(graph['coverage']) - len(labels)
    missing_edges = len(graph['edges']) - len(edges)
    if missing_nodes or missing_edges:
        lines.append(f'  note["Diagram omitted {missing_nodes} nodes and {missing_edges} edges"]')
    return '\n'.join(lines) + '\n'


def render(graph, formats, diagram_depth=2):
    validate(graph)
    require(formats and all(fmt in FORMATS for fmt in formats), 'Select a supported format')
    require(type(diagram_depth) is int and diagram_depth >= 0, 'Diagram depth must be nonnegative')
    graph = {**graph, **{table: sorted(graph[table], key=lambda row: tuple(row.get(k, '') for k in fields))
                         for table, fields in FIELDS.items()}}
    graph['edges'] = [{**edge, 'source_ids': sorted(edge['source_ids'])} for edge in graph['edges']]
    files = {}
    if 'json' in formats:
        files['graph.json'] = json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n'
    if 'csv' in formats:
        files.update({f'{table}.csv': csv_table(fields, graph[table]) for table, fields in FIELDS.items()})
        files['edge_sources.csv'] = csv_table((*FIELDS['edges'][:-1], 'source_id'), [
            {**edge, 'source_id': source} for edge in graph['edges'] for source in edge['source_ids']])
    if 'mermaid' in formats:
        files['graph.mmd'] = mermaid(graph, diagram_depth)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--out', type=Path, required=True, help='New output directory')
    parser.add_argument('--format', choices=FORMATS, action='append')
    parser.add_argument('--diagram-depth', type=int, default=2)
    args = parser.parse_args()
    try:
        files = render(json.loads(args.snapshot.read_text(encoding='utf-8')),
                       args.format or ['json'], args.diagram_depth)
        args.out.mkdir(parents=True, exist_ok=False)
        for name, contents in files.items():
            with (args.out / name).open('x', encoding='utf-8', newline='') as handle:
                handle.write(contents)
    except (OSError, ValueError) as exc:
        parser.exit(2, f'export_graph: {exc}\n')


if __name__ == '__main__':
    main()
