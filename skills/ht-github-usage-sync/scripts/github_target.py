"""Shared strict target identity for config and explicit deployment ledgers."""
import re

DEPLOYMENTS = {'enterprise_cloud': ('enterprise', 'enterprises'),
               'organization': ('organization', 'organizations')}


def target_identity(value):
    """Return (deployment, selected slug) without normalizing caller values."""
    deployment = value.get('deployment')
    if type(deployment) is not str or deployment not in DEPLOYMENTS:
        raise ValueError('github.deployment: Select enterprise_cloud or organization.')
    selected, _ = DEPLOYMENTS[deployment]
    other = 'organization' if selected == 'enterprise' else 'enterprise'
    slug = value.get(selected)
    if other in value:
        raise ValueError('github: Remove the target key incompatible with deployment, even when null.')
    if type(slug) is not str or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?', slug):
        raise ValueError('github: Supply the selected target slug using letters, digits and internal hyphens.')
    return deployment, slug


def billing_path_matches(path, deployment, slug, page):
    """Accept a billing entrypoint or its selected report, without rewriting URLs."""
    if deployment == 'enterprise_cloud':
        bases = (f'/enterprises/{slug}/billing',
                 f'/enterprises/{slug}/settings/billing')
    else:
        bases = (f'/organizations/{slug}/settings/billing',)
    return any(path in {base, base + '/', base + '/' + page, base + '/' + page + '/'}
               for base in bases)
