import { lookup } from 'node:dns/promises';

import { parseHTML } from 'linkedom';
import { Defuddle } from 'defuddle/node';
import ipaddr from 'ipaddr.js';
import { Agent, fetch as undiciFetch } from 'undici';


const FETCH_TIMEOUT_MS = 15000;
const MAX_REDIRECTS = 20;
const READER_BASE_URL = 'https://r.jina.ai/';
const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308]);

// Sites frequently 403 a bare Node UA; a Safari UA is what defuddle's own
// CLI recommends for exactly this reason.
const USER_AGENT =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
  + '(KHTML, like Gecko) Version/17.0 Safari/605.1.15';


export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}


function bareHostname(hostname) {
  return hostname.toLowerCase().replace(/^\[|\]$/g, '');
}


function isPublicAddress(address) {
  if (!ipaddr.isValid(address)) return false;
  return ipaddr.parse(address).range() === 'unicast';
}


async function waitForLookup(lookupPromise, signal) {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(signal.reason);
    signal.addEventListener('abort', onAbort, { once: true });
    lookupPromise.then(
      (records) => {
        signal.removeEventListener('abort', onAbort);
        if (signal.aborted) {
          reject(signal.reason);
          return;
        }
        resolve(records);
      },
      (error) => {
        signal.removeEventListener('abort', onAbort);
        reject(error);
      },
    );
  });
}


async function resolvePublicAddresses(parsed, lookupImpl, privateMessage, signal) {
  signal.throwIfAborted();
  const hostname = bareHostname(parsed.hostname);
  if (hostname === 'localhost' || hostname.endsWith('.local')) {
    throw new HttpError(400, privateMessage);
  }

  const records = ipaddr.isValid(hostname)
    ? [{ address: hostname, family: ipaddr.parse(hostname).kind() === 'ipv4' ? 4 : 6 }]
    : await waitForLookup(
      Promise.resolve(lookupImpl(hostname, { all: true, verbatim: true })),
      signal,
    );
  if (!Array.isArray(records) || records.length === 0) {
    throw new Error(`DNS returned no addresses for ${hostname}`);
  }
  if (records.some((record) => !isPublicAddress(record.address))) {
    throw new HttpError(400, privateMessage);
  }
  return records.map((record) => ({
    address: record.address,
    family: Number(record.family),
  }));
}


function pinnedDispatcher(records) {
  return new Agent({
    connect: {
      lookup(_hostname, options, callback) {
        const requestedFamily = typeof options === 'number'
          ? options
          : Number(options?.family || 0);
        const candidates = requestedFamily
          ? records.filter((record) => record.family === requestedFamily)
          : records;
        if (candidates.length === 0) {
          callback(new Error(`no validated DNS address for family ${requestedFamily}`));
          return;
        }
        if (typeof options === 'object' && options?.all) {
          callback(null, candidates);
          return;
        }
        callback(null, candidates[0].address, candidates[0].family);
      },
    },
  });
}


async function discardResponse(response) {
  if (response.body && !response.bodyUsed) {
    await response.body.cancel();
  }
}


async function closeAfter(dispatcher, operation) {
  try {
    return await operation();
  } finally {
    await dispatcher.close();
  }
}


function directFetchError(error) {
  if (error instanceof HttpError) return error;
  if (error.name === 'TimeoutError' || error.name === 'AbortError') {
    return new HttpError(504, `upstream fetch timed out after ${FETCH_TIMEOUT_MS}ms`);
  }
  return new HttpError(502, `upstream fetch failed: ${error.message}`);
}


async function fetchPublic(
  url,
  { fetchImpl, lookupImpl, headers, signal, initialPrivateMessage },
) {
  let current = new URL(url);
  for (let redirectCount = 0; redirectCount <= MAX_REDIRECTS; redirectCount += 1) {
    if (current.protocol !== 'http:' && current.protocol !== 'https:') {
      throw new HttpError(
        400,
        redirectCount === 0
          ? 'only http(s) URLs are supported'
          : 'redirect used an unsupported protocol',
      );
    }
    const addresses = await resolvePublicAddresses(
      current,
      lookupImpl,
      redirectCount === 0
        ? initialPrivateMessage
        : 'redirect led to a private or loopback address',
      signal,
    );
    const dispatcher = pinnedDispatcher(addresses);

    let response;
    try {
      response = await fetchImpl(current.href, {
        headers,
        redirect: 'manual',
        signal,
        dispatcher,
      });
    } catch (error) {
      await dispatcher.close();
      throw error;
    }

    const location = response.headers.get('location');
    if (REDIRECT_STATUSES.has(response.status) && location) {
      await closeAfter(dispatcher, () => discardResponse(response));
      if (redirectCount === MAX_REDIRECTS) {
        throw new Error(`too many redirects (>${MAX_REDIRECTS})`);
      }
      current = new URL(location, current);
      continue;
    }
    return { response, dispatcher };
  }
  throw new Error(`too many redirects (>${MAX_REDIRECTS})`);
}


function sanitizedReaderTarget(parsed) {
  const target = new URL(parsed.href);
  for (const key of [...target.searchParams.keys()]) {
    const lower = key.toLowerCase();
    if (lower === 'email' || lower.startsWith('utm_')) {
      target.searchParams.delete(key);
    }
  }
  return target.href;
}


function readerField(header, name) {
  const match = header.match(new RegExp(`^${name}:\\s*(.*)$`, 'mi'));
  return match?.[1]?.trim() || null;
}


async function extractWithReader(
  parsed,
  originalUrl,
  fetchImpl,
  lookupImpl,
  signal,
) {
  try {
    const { response, dispatcher } = await fetchPublic(
      `${READER_BASE_URL}${sanitizedReaderTarget(parsed)}`,
      {
        fetchImpl,
        lookupImpl,
        headers: { accept: 'text/plain' },
        signal,
        initialPrivateMessage: 'reader resolved to a private or loopback address',
      },
    );
    try {
      if (!response.ok) {
        await discardResponse(response);
        throw new Error(`reader returned HTTP ${response.status}`);
      }

      const contentType = response.headers.get('content-type') || '';
      if (!contentType.toLowerCase().startsWith('text/plain')) {
        await discardResponse(response);
        throw new Error(
          `reader returned ${contentType || 'no content type'}, not text/plain`,
        );
      }

      const body = await response.text();
      const match = body.match(/(?:^|\r?\n)Markdown Content:\s*\r?\n([\s\S]*)$/);
      const content = match?.[1]?.trim() || '';
      if (!content) {
        throw new Error('reader returned no article content');
      }
      const header = body.slice(0, match.index);

      return {
        title: readerField(header, 'Title'),
        author: null,
        description: null,
        site: parsed.hostname,
        published: readerField(header, 'Published Time'),
        word_count: content.split(/\s+/).length,
        url: originalUrl,
        content,
      };
    } finally {
      await dispatcher.close();
    }
  } catch (error) {
    const detail = error.name === 'TimeoutError' || error.name === 'AbortError'
      ? `reader fetch timed out within ${FETCH_TIMEOUT_MS}ms budget`
      : error.message;
    throw new HttpError(
      502,
      `upstream returned HTTP 403; reader fallback failed: ${detail}`,
    );
  }
}


export async function extract(
  url,
  fetchImpl = undiciFetch,
  lookupImpl = lookup,
  signal = AbortSignal.timeout(FETCH_TIMEOUT_MS),
) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    throw new HttpError(400, `not a URL: ${url}`);
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new HttpError(400, 'only http(s) URLs are supported');
  }

  let fetched;
  try {
    fetched = await fetchPublic(url, {
      fetchImpl,
      lookupImpl,
      headers: {
        'user-agent': USER_AGENT,
        accept: 'text/html,application/xhtml+xml',
      },
      signal,
      initialPrivateMessage: 'refusing to fetch a private or loopback address',
    });
  } catch (error) {
    throw directFetchError(error);
  }

  const { response, dispatcher } = fetched;
  if (!response.ok) {
    try {
      await closeAfter(dispatcher, () => discardResponse(response));
    } catch (error) {
      throw directFetchError(error);
    }
    if (response.status === 403) {
      return extractWithReader(parsed, url, fetchImpl, lookupImpl, signal);
    }
    throw new HttpError(502, `upstream returned HTTP ${response.status}`);
  }

  let html;
  try {
    html = await closeAfter(dispatcher, () => response.text());
  } catch (error) {
    throw directFetchError(error);
  }

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
