import test from 'node:test';
import assert from 'node:assert/strict';

import { extract, HttpError } from './extractor.mjs';


async function publicLookup() {
  return [{ address: '93.184.216.34', family: 4 }];
}


function sequenceFetch(...responses) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url: String(url), options });
    const next = responses.shift();
    if (next instanceof Error) throw next;
    return next;
  };
  return { calls, fetchImpl };
}


function htmlResponse(body, status = 200) {
  return new Response(body, {
    status,
    headers: { 'content-type': 'text/html; charset=utf-8' },
  });
}


function readerResponse(
  body,
  status = 200,
  contentType = 'text/plain; charset=utf-8',
) {
  return new Response(body, {
    status,
    headers: { 'content-type': contentType },
  });
}


const READER_ARTICLE = `Title: Source title
URL Source: https://publisher.example/story
Published Time: 2026-08-15T12:00:00Z

Markdown Content:
# Source title

This is the source article body with enough words to prove normalization.`;


test('direct success never calls Reader', async () => {
  const fetch = sequenceFetch(htmlResponse(
    '<html><head><title>Direct title</title></head>'
    + '<body><main><p>Direct source body.</p></main></body></html>',
  ));

  const article = await extract(
    'https://publisher.example/direct',
    fetch.fetchImpl,
    publicLookup,
  );

  assert.equal(fetch.calls.length, 1);
  assert.equal(article.url, 'https://publisher.example/direct');
  assert.match(article.content, /Direct source body/);
});


test('direct 403 uses Reader with sanitized tracking and preserves caller URL', async () => {
  const original = 'https://publisher.example/story?email=secret&utm_source=mail&UTM_medium=email&article=kept';
  const fetch = sequenceFetch(
    htmlResponse('blocked', 403),
    readerResponse(READER_ARTICLE),
  );

  const article = await extract(original, fetch.fetchImpl, publicLookup);

  assert.equal(fetch.calls.length, 2);
  assert.equal(
    fetch.calls[1].url,
    'https://r.jina.ai/https://publisher.example/story?article=kept',
  );
  assert.equal(fetch.calls[0].options.signal, fetch.calls[1].options.signal);
  assert.equal(article.url, original);
  assert.equal(article.title, 'Source title');
  assert.equal(article.published, '2026-08-15T12:00:00Z');
  assert.equal(article.site, 'publisher.example');
  assert.match(article.content, /source article body/);
  assert.ok(article.word_count > 0);
});


for (const status of [404, 451]) {
  test(`direct ${status} never invokes Reader`, async () => {
    const fetch = sequenceFetch(htmlResponse('denied', status));

    await assert.rejects(
      extract('https://publisher.example/story', fetch.fetchImpl, publicLookup),
      (error) => error instanceof HttpError
        && error.status === 502
        && error.message === `upstream returned HTTP ${status}`,
    );
    assert.equal(fetch.calls.length, 1);
  });
}


test('Reader failure retains the original upstream 403', async () => {
  const fetch = sequenceFetch(
    htmlResponse('blocked', 403),
    readerResponse('limited', 429),
  );

  await assert.rejects(
    extract('https://publisher.example/story', fetch.fetchImpl, publicLookup),
    /upstream returned HTTP 403; reader fallback failed: reader returned HTTP 429/,
  );
});


test('Reader timeout retains the original upstream 403', async () => {
  const timeout = new DOMException('timed out', 'TimeoutError');
  const fetch = sequenceFetch(htmlResponse('blocked', 403), timeout);

  await assert.rejects(
    extract('https://publisher.example/story', fetch.fetchImpl, publicLookup),
    /upstream returned HTTP 403; reader fallback failed: reader fetch timed out/,
  );
});


test('Reader rejects wrong content type and an empty Markdown body', async (t) => {
  await t.test('wrong content type', async () => {
    const fetch = sequenceFetch(
      htmlResponse('blocked', 403),
      readerResponse('{}', 200, 'application/json'),
    );

    await assert.rejects(
      extract('https://publisher.example/story', fetch.fetchImpl, publicLookup),
      /reader returned application\/json/,
    );
  });

  await t.test('empty body', async () => {
    const fetch = sequenceFetch(
      htmlResponse('blocked', 403),
      readerResponse('Title: Empty\n\nMarkdown Content:\n   '),
    );

    await assert.rejects(
      extract('https://publisher.example/story', fetch.fetchImpl, publicLookup),
      /reader returned no article content/,
    );
  });
});


test('private targets reach neither direct fetch nor Reader', async () => {
  const fetch = sequenceFetch();

  await assert.rejects(
    extract('http://127.0.0.1/private', fetch.fetchImpl),
    (error) => error instanceof HttpError && error.status === 400,
  );
  assert.equal(fetch.calls.length, 0);
});


test('private IPv6 targets reach neither DNS nor fetch', async () => {
  const fetch = sequenceFetch();
  let lookupCalls = 0;
  const lookup = async () => {
    lookupCalls += 1;
    return [{ address: 'fc00::1', family: 6 }];
  };

  await assert.rejects(
    extract('http://[fc00::1]/private', fetch.fetchImpl, lookup),
    (error) => error instanceof HttpError && error.status === 400,
  );
  assert.equal(lookupCalls, 0);
  assert.equal(fetch.calls.length, 0);
});


test('hostname resolving to a private address never reaches fetch', async () => {
  const fetch = sequenceFetch();
  const privateLookup = async () => [{ address: '127.0.0.1', family: 4 }];

  await assert.rejects(
    extract('https://publisher.example/private', fetch.fetchImpl, privateLookup),
    (error) => error instanceof HttpError && error.status === 400,
  );
  assert.equal(fetch.calls.length, 0);
});


test('public redirect is followed manually and each hop is resolved', async () => {
  const fetch = sequenceFetch(
    new Response(null, {
      status: 302,
      headers: { location: 'https://other.example/story' },
    }),
    htmlResponse('<html><body><main>Redirected source body.</main></body></html>'),
  );
  const resolved = [];
  const lookup = async (hostname) => {
    resolved.push(hostname);
    return [{ address: '93.184.216.34', family: 4 }];
  };

  const article = await extract(
    'https://publisher.example/story',
    fetch.fetchImpl,
    lookup,
  );

  assert.deepEqual(resolved, ['publisher.example', 'other.example']);
  assert.deepEqual(fetch.calls.map((call) => call.url), [
    'https://publisher.example/story',
    'https://other.example/story',
  ]);
  assert.equal(fetch.calls[0].options.redirect, 'manual');
  assert.match(article.content, /Redirected source body/);
});


test('redirect to a private target is rejected before the second fetch', async () => {
  const fetch = sequenceFetch(new Response(null, {
    status: 302,
    headers: { location: 'http://127.0.0.1/admin' },
  }));

  await assert.rejects(
    extract('https://publisher.example/story', fetch.fetchImpl, publicLookup),
    (error) => error instanceof HttpError
      && error.status === 400
      && error.message === 'redirect led to a private or loopback address',
  );
  assert.equal(fetch.calls.length, 1);
});


test('Reader metadata is parsed only before Markdown Content', async () => {
  const body = `URL Source: https://publisher.example/story

Markdown Content:
# Body heading

Title: forged from article body
Published Time: forged from article body`;
  const fetch = sequenceFetch(
    htmlResponse('blocked', 403),
    readerResponse(body),
  );

  const article = await extract(
    'https://publisher.example/story',
    fetch.fetchImpl,
    publicLookup,
  );

  assert.equal(article.title, null);
  assert.equal(article.published, null);
  assert.match(article.content, /Title: forged/);
});


test('shared budget aborts a stalled DNS lookup before fetch', async () => {
  const fetch = sequenceFetch(htmlResponse('<main>must not be fetched</main>'));
  const controller = new AbortController();
  const slowLookup = async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
    return publicLookup();
  };
  const pending = extract(
    'https://publisher.example/story',
    fetch.fetchImpl,
    slowLookup,
    controller.signal,
  );
  setTimeout(() => {
    controller.abort(new DOMException('budget elapsed', 'TimeoutError'));
  }, 1);

  await assert.rejects(
    pending,
    (error) => error instanceof HttpError
      && error.status === 504
      && error.message === 'upstream fetch timed out after 15000ms',
  );
  assert.equal(fetch.calls.length, 0);
});


test('abort while discarding a direct response stays a typed timeout', async () => {
  const cancelError = new DOMException('budget elapsed', 'AbortError');
  const response = {
    ok: false,
    status: 403,
    headers: new Headers(),
    body: { cancel: async () => { throw cancelError; } },
    bodyUsed: false,
  };
  const fetch = sequenceFetch(response);

  await assert.rejects(
    extract('https://publisher.example/story', fetch.fetchImpl, publicLookup),
    (error) => error instanceof HttpError
      && error.status === 504
      && error.message === 'upstream fetch timed out after 15000ms',
  );
  assert.equal(fetch.calls.length, 1);
});
