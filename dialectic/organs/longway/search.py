"""Search adapters and durable result provenance; credentials never enter receipts.

Protocol references verified 2026-10-28:
https://api-dashboard.search.brave.com/app/documentation/web-search
https://exa.ai/docs/reference/search
"""
import os
from uuid import uuid4

import httpx


def configuration():
    provider = os.environ.get('LONGWAY_SEARCH_PROVIDER', 'none').strip().lower()
    if provider not in ('none', 'brave', 'exa'):
        raise RuntimeError('LONGWAY_SEARCH_PROVIDER must be none, brave or exa')
    key = os.environ.get('LONGWAY_SEARCH_KEY', '').strip()
    if provider != 'none' and not key:
        raise RuntimeError('LONGWAY_SEARCH_KEY is required for the configured search provider')
    return provider, key


async def brave(client, key, query, count):
    response = await client.get('https://api.search.brave.com/res/v1/web/search',
        params={'q': query, 'count': count}, headers={'X-Subscription-Token': key})
    response.raise_for_status()
    return [{'url': r['url'], 'title': r.get('title'), 'snippet': r.get('description')}
            for r in response.json().get('web', {}).get('results', [])[:count]]


async def exa(client, key, query, count):
    response = await client.post('https://api.exa.ai/search', headers={'x-api-key': key},
        json={'query': query, 'numResults': count, 'type': 'auto', 'contents': {'highlights': True}})
    response.raise_for_status()
    return [{'url': r['url'], 'title': r.get('title'), 'snippet': '\n'.join(r.get('highlights') or []) or r.get('text')}
            for r in response.json().get('results', [])[:count]]


async def search(db, run_id, query, count=8, *, client=None):
    provider, key = configuration()
    if provider == 'none':
        raise ValueError('Search is not configured')
    query = ' '.join(query.split())
    if not query or len(query) > 600 or not 1 <= count <= 8:
        raise ValueError('Search needs a place query of 1–600 characters and count 1–8')
    owned = client is None
    client = client or httpx.AsyncClient(timeout=25)
    try:
        # Do not expose arbitrary upstream error bodies or request headers.
        try:
            results = await {'brave': brave, 'exa': exa}[provider](client, key, query, count)
        except Exception:
            raise RuntimeError(f'{provider} search failed') from None
    finally:
        if owned:
            await client.aclose()
    async with db.transaction():
        status = await db.fetchval('SELECT status FROM longway_scout_runs WHERE id=$1 FOR UPDATE', run_id)
        if status != 'running':
            raise ValueError('Scout run is no longer running')
        rows = []
        for rank, item in enumerate(results, 1):
            row = await db.fetchrow('''INSERT INTO longway_search_results
                (id,run_id,provider,query,rank,url,title,snippet) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                RETURNING id,url,title,snippet''', uuid4(), run_id, provider, query, rank,
                item['url'], item['title'], item['snippet'])
            rows.append(dict(row, id=str(row['id'])))
        await db.execute('UPDATE longway_scout_runs SET searches=searches+1 WHERE id=$1', run_id)
    return rows
