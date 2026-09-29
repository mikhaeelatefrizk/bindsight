// SPDX-License-Identifier: AGPL-3.0-or-later
// The hosted URL serves the CI-published GitHub workspace. It accepts no data,
// credentials or arbitrary upstream URL, and runs no scientific computation.
const ORIGIN = 'https://mikhaeelatefrizk.github.io';
const PREFIX = '/bindsight/workspace';

export function upstreamPath(pathname) {
  if (pathname === '/' || pathname === '/index.html') return `${PREFIX}/index.html`;
  if (pathname === '/evidence.json' || pathname === '/release.json') return PREFIX + pathname;
  if (!/^\/(assets|structures|sequences|downloads)\/[A-Za-z0-9_.\/-]+$/.test(pathname)) return null;
  if (pathname.split('/').some(segment => segment === '..' || segment === '.')) return null;
  return PREFIX + pathname;
}

export async function serve(request, fetcher = fetch, headerTimeoutMs = 15000, diagnose = record => console.error(JSON.stringify(record))) {
  if (!['GET', 'HEAD'].includes(request.method)) {
    return new Response('This public website is read-only. Analyses run on your computer.', {status: 405, headers: {Allow: 'GET, HEAD'}});
  }
  const path = upstreamPath(new URL(request.url).pathname);
  if (!path) return new Response('Not found', {status: 404});
  let failure = 'fetch_error';
  let upstreamStatus = null;
  let headersTimedOut = false;
  try {
    // Bound waiting for headers without cutting off a valid slow ZIP download.
    const controller = new AbortController();
    const timer = setTimeout(() => {headersTimedOut = true; controller.abort();}, headerTimeoutMs);
    let upstream;
    try {
      upstream = await fetcher(ORIGIN + path, {
        method: request.method,
        // workerd rejects redirect:'error' even before sending the request.
        // Manual mode never follows; reject redirect responses explicitly below.
        redirect: 'manual',
        signal: controller.signal,
        headers: {Accept: '*/*'},
        cf: {cacheTtl: 60, cacheEverything: true},
      });
    } finally {
      clearTimeout(timer);
    }
    upstreamStatus = upstream.status;
    if (upstream.status >= 300 && upstream.status < 400) {
      failure = 'upstream_redirect';
      throw new Error('Published artifact redirected');
    }
    if (!upstream.ok) {
      failure = 'upstream_status';
      throw new Error('Published artifact unavailable');
    }
    failure = 'response_error';
    const headers = new Headers();
    // Fetch may decode an upstream body; let the host compute its final length.
    for (const key of ['Content-Type', 'ETag', 'Last-Modified']) {
      if (upstream.headers.has(key)) headers.set(key, upstream.headers.get(key));
    }
    headers.set('Cache-Control', 'public, max-age=60, must-revalidate');
    headers.set('X-Content-Type-Options', 'nosniff');
    headers.set('Referrer-Policy', 'no-referrer');
    return new Response(request.method === 'HEAD' ? null : upstream.body, {status: 200, headers});
  } catch (error) {
    // Only bounded categories and status are logged, never visitor URLs,
    // headers, credentials, Location values, upstream bodies or error messages.
    const errorType = ['TypeError', 'AbortError', 'TimeoutError', 'Error'].includes(error?.name) ? error.name : 'UnknownError';
    try {
      diagnose({event: 'bindsight_relay_unavailable', reason: headersTimedOut ? 'header_timeout' : failure, upstream_status: upstreamStatus, error_type: errorType});
    } catch { /* Diagnostics must not prevent the recovery page. */ }
    const message = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Bindsight · temporarily unavailable</title><main><h1>The research workspace is temporarily unavailable at this address.</h1><p>This relay could not reach the published workspace. You can open its direct publication or try again shortly.</p><p><a href="https://mikhaeelatefrizk.github.io/bindsight/workspace/">Open the research workspace directly</a></p><p><a href="https://github.com/mikhaeelatefrizk/bindsight">View the source on GitHub</a></p></main></html>';
    return new Response(request.method === 'HEAD' ? null : message, {status: 503, headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'Retry-After': '60'}});
  }
}

export default {fetch: request => serve(request)};
