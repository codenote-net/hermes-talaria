#!/usr/bin/env python3
"""Read-only GitHub scope inventory. Python standard library plus authenticated gh."""
import argparse
from datetime import datetime, timezone
import json
import os
import re
import subprocess
from urllib.parse import urlsplit


ORG_QUERY = '''query($login:String!,$cursor:String) {
  organization(login:$login) {
    repositories(first:100,after:$cursor) {
      totalCount pageInfo { hasNextPage endCursor }
      nodes { id nameWithOwner url visibility isArchived isFork hasIssuesEnabled
        viewerPermission defaultBranchRef { name target { oid } } }
    }
  }
}'''
ENTERPRISE_QUERY = '''query($slug:String!,$cursor:String) {
  enterprise(slug:$slug) {
    organizations(first:100,after:$cursor) {
      totalCount pageInfo { hasNextPage endCursor } nodes { id login }
    }
  }
}'''


def parse_scope(value):
    url = urlsplit(value)
    if (url.scheme != 'https' or url.netloc != 'github.com' or url.query or
            url.fragment or '?' in value or '#' in value):
        raise ValueError('Expected a clean github.com scope URL without credentials or query')
    match = re.fullmatch(r'/(orgs|enterprises)/([A-Za-z0-9][A-Za-z0-9-]*)/'
                         r'(repositories|organizations)/?', url.path)
    if not match or (match[1], match[3]) not in {
            ('orgs', 'repositories'), ('enterprises', 'organizations')}:
        raise ValueError('Expected an organization repositories or enterprise organizations URL')
    return ('organization' if match[1] == 'orgs' else 'enterprise', match[2])


def unwrap(response):
    if response.get('errors') or not isinstance(response.get('data'), dict):
        raise ValueError('GraphQL failed or returned partial data; inventory is incomplete')
    return response['data']


def gh_graphql(query, variables):
    result = subprocess.run(
        ['gh', 'api', '--hostname', 'github.com', 'graphql', '--input', '-'],
        input=json.dumps({'query': query, 'variables': variables}),
        capture_output=True, text=True, check=False, timeout=120)
    if result.returncode:
        # Do not echo arbitrary server response text or credential-bearing diagnostics.
        raise ValueError('gh API request failed; check authentication, access and rate limits')
    return unwrap(json.loads(result.stdout))


def collect(fetch):
    cursor = None
    cursors = set()
    ids = set()
    items = []
    total = None
    while True:
        page = fetch(cursor)
        if not isinstance(page, dict):
            raise ValueError('Missing connection; inventory is incomplete')
        count = page['totalCount']
        if type(count) is not int or count < 0 or (total is not None and count != total):
            raise ValueError('Connection total changed; restart discovery')
        total = count
        for node in page['nodes']:
            if not isinstance(node, dict) or not node.get('id') or node['id'] in ids:
                raise ValueError('Null or duplicate node; restart discovery')
            ids.add(node['id'])
            items.append(node)
        info = page['pageInfo']
        if type(info['hasNextPage']) is not bool:
            raise ValueError('Invalid pagination status')
        if not info['hasNextPage']:
            break
        cursor = info['endCursor']
        if not cursor or cursor in cursors:
            raise ValueError('Missing or repeated pagination cursor')
        cursors.add(cursor)
    if len(items) != total:
        raise ValueError('Connection count mismatch; inventory is incomplete')
    return items


def inventory(kind, slug, api=gh_graphql):
    def org_page(cursor):
        data = api(ENTERPRISE_QUERY, {'slug': slug, 'cursor': cursor})
        return (data.get('enterprise') or {}).get('organizations')
    organizations = collect(org_page) if kind == 'enterprise' else [{'login': slug}]
    result = []
    repo_ids = set()
    for org in organizations:
        def repo_page(cursor):
            data = api(ORG_QUERY, {'login': org['login'], 'cursor': cursor})
            return (data.get('organization') or {}).get('repositories')
        repos = collect(repo_page)
        for repo in repos:
            if repo['id'] in repo_ids:
                raise ValueError('Repository appeared in multiple organizations; restart discovery')
            repo_ids.add(repo['id'])
        result.append({**org, 'repositories': sorted(repos, key=lambda r: r['nameWithOwner'])})
    return {
        'schema_version': 1, 'host': 'github.com', 'scope_type': kind, 'scope': slug,
        'scanned_at': datetime.now(timezone.utc).isoformat(),
        'pagination_complete': True, 'administrative_coverage_verified': False,
        'organization_count': len(result), 'repository_count': len(repo_ids),
        'organizations': sorted(result, key=lambda o: o['login']),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scope_url')
    parser.add_argument('--output', required=True, help='New private JSON file outside Git')
    args = parser.parse_args()
    try:
        kind, slug = parse_scope(args.scope_url)
        if os.path.lexists(args.output):
            raise ValueError('Output path already exists; choose a fresh path')
        result = inventory(kind, slug)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
        print(json.dumps({k: result[k] for k in (
            'organization_count', 'repository_count', 'pagination_complete',
            'administrative_coverage_verified')}))
    except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f'Inventory failed ({type(exc).__name__}); no complete inventory claimed.\n')


if __name__ == '__main__':
    main()
