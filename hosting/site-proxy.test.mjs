// SPDX-License-Identifier: AGPL-3.0-or-later
import assert from 'node:assert/strict';
import test from 'node:test';
import {serve, upstreamPath} from './site-proxy.mjs';

test('only authored public artifact paths can reach the fixed upstream', () => {
  assert.equal(upstreamPath('/'), '/bindsight/workspace/index.html');
  assert.equal(upstreamPath('/downloads/bindsight-local.zip'), '/bindsight/workspace/downloads/bindsight-local.zip');
  for (const path of ['/api/workbench/jobs', '/.git/config', '/assets/../../secret', '//example.com', '/assets/%2e%2e/secret']) assert.equal(upstreamPath(path), null);
});

test('no cookies, tokens, query strings, or visitor headers are forwarded', async () => {
  let destination, options;
  const response = await serve(new Request('https://site.test/evidence.json?token=private', {headers: {Cookie: 'private', Authorization: 'Bearer private'}}), async (url, init) => {
    destination = url; options = init;
    return new Response('{"real":"artifact"}', {headers: {'Content-Type':'application/json', 'Set-Cookie':'discard=1'}});
  });
  assert.equal(destination, 'https://mikhaeelatefrizk.github.io/bindsight/workspace/evidence.json');
  assert.deepEqual(options.headers, {Accept: '*/*'});
  assert.equal(options.redirect, 'manual');
  assert.equal(response.headers.get('Set-Cookie'), null);
  assert.equal(response.headers.get('Content-Length'), null);
  assert.equal(response.headers.get('Cache-Control'), 'public, max-age=60, must-revalidate');
  assert.equal(await response.text(), '{"real":"artifact"}');
});

test('uploads and unknown routes are rejected before any upstream access', async () => {
  const forbidden = () => {throw new Error('must not fetch');};
  assert.equal((await serve(new Request('https://site.test/', {method:'POST', body:'private data'}), forbidden)).status, 405);
  assert.equal((await serve(new Request('https://site.test/api/workbench/jobs'), forbidden)).status, 404);
});

test('upstream failures return an honest uncached unavailable page', async () => {
  const response = await serve(new Request('https://site.test/'), async () => new Response('missing', {status:404}));
  assert.equal(response.status, 503);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.match(await response.text(), /temporarily unavailable/);
});

test('downloads are streamed intact and HEAD has no body', async () => {
  const bytes = new Uint8Array([80,75,3,4,0,255]);
  const stub = async () => new Response(bytes, {headers:{'Content-Type':'application/zip'}});
  const response = await serve(new Request('https://site.test/downloads/bindsight-local.zip'), stub);
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), bytes);
  assert.equal(await (await serve(new Request('https://site.test/', {method:'HEAD'}), stub)).text(), '');
});

test('a valid slow body outlives the header deadline', async () => {
  let signal;
  const response = await serve(new Request('https://site.test/downloads/bindsight-local.zip'), async (_, options) => {
    signal = options.signal;
    return new Response(new ReadableStream({
      start(controller) {
        signal.addEventListener('abort', () => controller.error(new Error('stream aborted')));
        setTimeout(() => {controller.enqueue(new Uint8Array([80,75])); controller.close();}, 40);
      },
    }));
  }, 5);
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), new Uint8Array([80,75]));
  assert.equal(signal.aborted, false);
});

test('an upstream that never supplies headers times out honestly', async () => {
  const diagnostics = [];
  const response = await serve(new Request('https://site.test/'), (_, options) => new Promise((_, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('header timeout')));
  }), 5, record => diagnostics.push(record));
  assert.equal(response.status, 503);
  assert.equal(diagnostics[0].reason, 'header_timeout');
});

test('redirects are not followed and never become a successful artifact', async () => {
  for (const status of [301, 302, 303, 307, 308]) {
    let calls = 0;
    const diagnostics = [];
    const response = await serve(new Request('https://site.test/'), async (_, options) => {
      calls += 1;
      assert.equal(options.redirect, 'manual');
      return new Response(null, {status, headers:{Location:'https://untrusted.test/?secret=private'}});
    }, 15000, record => diagnostics.push(record));
    assert.equal(calls, 1);
    assert.equal(response.status, 503);
    assert.deepEqual(diagnostics, [{event:'bindsight_relay_unavailable', reason:'upstream_redirect', upstream_status:status, error_type:'Error'}]);
    assert.equal(response.headers.get('Location'), null);
  }
});

test('non-success statuses have bounded diagnostics and a direct recovery link', async () => {
  for (const status of [404, 429, 500, 503]) {
    const diagnostics = [];
    const response = await serve(new Request('https://site.test/?token=private'), async () => new Response('private upstream details', {status}), 15000, record => diagnostics.push(record));
    assert.equal(response.status, 503);
    assert.equal(diagnostics[0].reason, 'upstream_status');
    assert.equal(diagnostics[0].upstream_status, status);
    const body = await response.text();
    assert.match(body, /href="https:\/\/mikhaeelatefrizk.github.io\/bindsight\/workspace\/"/);
    assert.doesNotMatch(body + JSON.stringify(diagnostics), /private/);
  }
});

test('fetch exception details are not exposed and logging cannot break recovery', async () => {
  const diagnostics = [];
  const fail = async () => {throw new TypeError('secret query token and headers');};
  const response = await serve(new Request('https://site.test/'), fail, 15000, record => diagnostics.push(record));
  assert.deepEqual(diagnostics, [{event:'bindsight_relay_unavailable', reason:'fetch_error', upstream_status:null, error_type:'TypeError'}]);
  assert.doesNotMatch(await response.text(), /secret query/);
  assert.equal((await serve(new Request('https://site.test/'), fail, 15000, () => {throw new Error('logger unavailable');})).status, 503);
});
