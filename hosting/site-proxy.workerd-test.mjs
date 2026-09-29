// SPDX-License-Identifier: AGPL-3.0-or-later
// Run with BINDSIGHT_MINIFLARE_DIR pointing to the isolated pinned installation.
// This uses real workerd Request construction; the upstream body is a labelled
// test fixture, so no network or scientific evidence is involved.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import path from 'node:path';
import test from 'node:test';

if (!process.env.BINDSIGHT_MINIFLARE_DIR) throw new Error('Set BINDSIGHT_MINIFLARE_DIR to the isolated Miniflare installation');
const runtimeRequire = createRequire(path.resolve(process.env.BINDSIGHT_MINIFLARE_DIR, 'package.json'));
const {Miniflare, convertV4MiniflareOptions} = runtimeRequire('miniflare');
const runtimeVersion = runtimeRequire('miniflare/package.json').version;
assert.equal(runtimeVersion, '5.20260926.1-alpha', 'Use the documented pinned test runtime');
const source = await readFile(new URL('./site-proxy.mjs', import.meta.url), 'utf8');
const originalDefault = 'export default {fetch: request => serve(request)};';
assert.ok(source.includes(originalDefault), 'The test must replace the actual relay entrypoint');

test('actual workerd rejects the old redirect option before a request is sent', async () => {
  const worker = new Miniflare(convertV4MiniflareOptions({modules:true, compatibilityDate:'2026-09-26', script:`
    export default {fetch() {
      try {new Request('https://example.test/', {redirect:'error'}); return Response.json({accepted:true});}
      catch(error) {return Response.json({accepted:false, name:error.name, message:error.message});}
    }};
  `}));
  try {
    const result = await (await worker.dispatchFetch('https://fixture.test/')).json();
    assert.equal(result.accepted, false);
    assert.equal(result.name, 'TypeError');
    assert.match(result.message, /Invalid redirect value/);
  } finally {await worker.dispose();}
});

test('actual workerd accepts the relay request and rejects fixture redirects', async () => {
  const entrypoint = `export default {fetch: request => {
    const fixtureStatus = new URL(request.url).searchParams.has('redirect') ? 302 : 200;
    return serve(request, async (url, options) => {
      // Unlike a Node-only fetch stub, this enforces the real runtime options.
      const outgoing = new Request(url, options);
      if (outgoing.redirect !== 'manual') throw new Error('Unexpected redirect policy');
      return new Response(fixtureStatus === 200 ? 'synthetic runtime test fixture' : null,
        {status:fixtureStatus, headers:fixtureStatus === 302 ? {Location:'https://untrusted.test/'} : {'Content-Type':'text/plain'}});
    }, 15000, () => {});
  }};`;
  const worker = new Miniflare(convertV4MiniflareOptions({modules:true, compatibilityDate:'2026-09-26', script:source.replace(originalDefault, entrypoint)}));
  try {
    const response = await worker.dispatchFetch('https://fixture.test/');
    assert.equal(response.status, 200);
    assert.equal(await response.text(), 'synthetic runtime test fixture');
    const redirected = await worker.dispatchFetch('https://fixture.test/?redirect');
    assert.equal(redirected.status, 503);
    assert.equal(redirected.headers.get('Location'), null);
    assert.match(await redirected.text(), /Open the research workspace directly/);
  } finally {await worker.dispose();}
});
