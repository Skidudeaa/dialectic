import { parseHTML } from 'linkedom';
import { Defuddle } from 'defuddle/node';


const FETCH_TIMEOUT_MS = 15000;
const READER_BASE_URL = 'https://r.jina.ai/';

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


// The LLM can be handed any URL; the sidecar must not become a proxy into
// loopback/RFC1918 services (the desk, postgres, cloud metadata, ...).
function isPrivateHost(hostname) {
  const h = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  return (
    h === 'localhost'
    || h === '::1'
    || h.endsWith('.local')
    || /^127\./.test(h)
    || /^10\./.test(h)
    || /^192\.168\./.test(h)
    || /^169\.254\./.test(h)
    || /^172\.(1[6-9]|2\d|3[01])\./.test(h)
    || /^0\./.test(h)
  );
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


function readerField(body, name) {
  const match = body.match(new RegExp(`^${name}:\\s*(.*)$`, 'mi'));
  return match?.[1]?.trim() || null;
}


async function extractWithReader(parsed, originalUrl, fetchImpl, signal) {
  try {
    const response = await fetchImpl(
      `${READER_BASE_URL}${sanitizedReaderTarget(parsed)}`,
      {
        headers: { accept: 'text/plain' },
        redirect: 'follow',
        signal,
      },
    );
    if (!response.ok) {
      throw new Error(`reader returned HTTP ${response.status}`);
    }

    const contentType = response.headers.get('content-type') || '';
    if (!contentType.toLowerCase().startsWith('text/plain')) {
      throw new Error(`reader returned ${contentType || 'no content type'}, not text/plain`);
    }

    const body = await response.text();
    const match = body.match(/(?:^|\r?\n)Markdown Content:\s*\r?\n([\s\S]*)$/);
    const content = match?.[1]?.trim() || '';
    if (!content) {
      throw new Error('reader returned no article content');
    }

    return {
      title: readerField(body, 'Title'),
      author: null,
      description: null,
      site: parsed.hostname,
      published: readerField(body, 'Published Time'),
      word_count: content.split(/\s+/).length,
      url: originalUrl,
      content,
    };
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


export async function extract(url, fetchImpl = fetch) {
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

  const signal = AbortSignal.timeout(FETCH_TIMEOUT_MS);
  let response;
  try {
    response = await fetchImpl(url, {
      headers: {
        'user-agent': USER_AGENT,
        accept: 'text/html,application/xhtml+xml',
      },
      redirect: 'follow',
      signal,
    });
  } catch (error) {
    if (error.name === 'TimeoutError' || error.name === 'AbortError') {
      throw new HttpError(504, `upstream fetch timed out after ${FETCH_TIMEOUT_MS}ms`);
    }
    throw new HttpError(502, `upstream fetch failed: ${error.message}`);
  }
  if (!response.ok) {
    if (response.status === 403) {
      return extractWithReader(parsed, url, fetchImpl, signal);
    }
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
    } catch (error) {
      if (error instanceof HttpError) throw error;
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
