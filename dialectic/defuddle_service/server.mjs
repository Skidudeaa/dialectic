// defuddle_service/server.mjs — local article-extraction sidecar for dialectic.
//
// WHY a service and not a library call: dialectic's backend is Python;
// defuddle is Node-only. This is the same sidecar shape tradingDesk already
// uses (llm/tradingdesk_client.py talks to 127.0.0.1:8006) — a tiny local
// HTTP service the tool registry calls, degrading gracefully when it is down.
//
// Contract:
//   GET  /health            -> {"ok": true}
//   POST /extract {url}     -> {title, author, description, site, published,
//                               word_count, url, content}   (content = Markdown)
//   errors                  -> {"error": "..."} with 400 / 502 / 504

import http from 'node:http';
import { parseHTML } from 'linkedom';
import { Defuddle } from 'defuddle/node';

const HOST = process.env.DEFUDDLE_HOST || '127.0.0.1';
const PORT = Number(process.env.DEFUDDLE_PORT || 8010);
const FETCH_TIMEOUT_MS = 15000;
const MAX_BODY_BYTES = 64 * 1024;

// Sites frequently 403 a bare Node UA; a Safari UA is what defuddle's own
// CLI recommends for exactly this reason.
const USER_AGENT =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 ' +
  '(KHTML, like Gecko) Version/17.0 Safari/605.1.15';

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// The LLM can be handed any URL; the sidecar must not become a proxy into
// loopback/RFC1918 services (the desk, postgres, cloud metadata, ...).
function isPrivateHost(hostname) {
  const h = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  return (
    h === 'localhost' ||
    h === '::1' ||
    h.endsWith('.local') ||
    /^127\./.test(h) ||
    /^10\./.test(h) ||
    /^192\.168\./.test(h) ||
    /^169\.254\./.test(h) ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(h) ||
    /^0\./.test(h)
  );
}

function send(res, status, payload) {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(payload));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(new HttpError(400, 'request body too large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

async function extract(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    throw new HttpError(400, `not a URL: ${url}`);
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new HttpError(400, 'only http(s) URLs are supported');
  }
  if (isPrivateHost(parsed.hostname)) {
    throw new HttpError(400, 'refusing to fetch a private or loopback address');
  }

  let response;
  try {
    response = await fetch(url, {
      headers: {
        'user-agent': USER_AGENT,
        accept: 'text/html,application/xhtml+xml',
      },
      redirect: 'follow',
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
  } catch (e) {
    if (e.name === 'TimeoutError' || e.name === 'AbortError') {
      throw new HttpError(504, `upstream fetch timed out after ${FETCH_TIMEOUT_MS}ms`);
    }
    throw new HttpError(502, `upstream fetch failed: ${e.message}`);
  }
  if (!response.ok) {
    throw new HttpError(502, `upstream returned HTTP ${response.status}`);
  }
  // A redirect can still land on a private address even when the original
  // URL was public — re-check where we actually ended up.
  if (response.url) {
    try {
      const landed = new URL(response.url);
      if (isPrivateHost(landed.hostname)) {
        throw new HttpError(400, 'redirect led to a private or loopback address');
      }
    } catch (e) {
      if (e instanceof HttpError) throw e;
    }
  }

  const html = await response.text();
  const { document } = parseHTML(html);
  const result = await Defuddle(document, url, { markdown: true });

  return {
    title: result.title ?? null,
    author: result.author ?? null,
    description: result.description ?? null,
    site: result.site ?? null,
    published: result.published ?? null,
    word_count: result.wordCount ?? null,
    url,
    content: result.content ?? '',
  };
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === 'GET' && req.url === '/health') {
      return send(res, 200, { ok: true });
    }
    if (req.method !== 'POST' || req.url !== '/extract') {
      return send(res, 404, { error: 'not found' });
    }

    let payload;
    try {
      payload = JSON.parse(await readBody(req));
    } catch (e) {
      if (e instanceof HttpError) throw e;
      return send(res, 400, { error: 'request body must be JSON' });
    }
    const url = typeof payload?.url === 'string' ? payload.url.trim() : '';
    if (!url) {
      return send(res, 400, { error: 'url is required' });
    }

    const article = await extract(url);
    return send(res, 200, article);
  } catch (e) {
    const status = e instanceof HttpError ? e.status : 500;
    if (status === 500) console.error(e);
    return send(res, status, { error: e.message });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`defuddle service listening on http://${HOST}:${PORT}`);
});
