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
import { extract, HttpError } from './extractor.mjs';

const HOST = process.env.DEFUDDLE_HOST || '127.0.0.1';
const PORT = Number(process.env.DEFUDDLE_PORT || 8010);
const MAX_BODY_BYTES = 64 * 1024;

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
