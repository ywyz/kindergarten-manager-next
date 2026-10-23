/**
 * R09 cleanup probe: executes the exact install/cleanup JS strings exported by
 * desktop/d1_main.py (passed via env by test_d3_h2_guard.py). It does not copy
 * or simplify the production algorithm.
 *
 * Each case installs the delayed-GET wrapper, starts one matching GET, simulates
 * a DOM-assertion failure, then runs the real cleanup JS in finally. It asserts:
 * - the suspended promise settles (cleanup did not pre-set __h2ReleaseCalled);
 * - the controlled real fetch was called exactly once;
 * - window.fetch is restored;
 * - ordinary cleanup, missing __h2CleanupFetch fallback, and a throwing cleanup
 *   hook all behave without losing the original DOM error.
 */
import assert from 'node:assert/strict'

const installJs = process.env.H2_INSTALL_JS
const cleanupJs = process.env.H2_CLEANUP_JS
assert.ok(installJs, 'H2_INSTALL_JS missing')
assert.ok(cleanupJs, 'H2_CLEANUP_JS missing')

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function waitFor(condition, what, timeout = 500) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (condition()) return
    await sleep(5)
  }
  throw new Error(`timed out waiting for ${what}`)
}

async function runCase(name, mode) {
  let realCalls = 0
  const realFetch = async (url) => {
    realCalls += 1
    return { ok: true, url: String(url) }
  }
  globalThis.window = { fetch: realFetch }
  eval(installJs)
  const pending = window.fetch('/api/daily-plans/p1', { method: 'GET' })
  await waitFor(() => window.__h2DelayedGetStarted === true, `${name} delayed start`)

  if (mode === 'fallback') {
    delete window.__h2CleanupFetch
  } else if (mode === 'cleanup-throws') {
    window.__h2CleanupFetch = () => {
      throw new Error('cleanup boom')
    }
  }

  let original = null
  let cleanupError = null
  try {
    throw new Error('DOM assertion failed')
  } catch (error) {
    original = error
  } finally {
    try {
      eval(cleanupJs)
    } catch (error) {
      cleanupError = error
    }
  }

  const settled = await Promise.race([
    pending.then((value) => ({ timedOut: false, value })),
    sleep(200).then(() => ({ timedOut: true })),
  ])
  assert.equal(settled.timedOut, false, `${name}: suspended GET did not settle`)
  assert.equal(realCalls, 1, `${name}: controlled fetch must run exactly once`)
  assert.equal(window.fetch, window.__h2RealFetch, `${name}: fetch not restored`)
  assert.equal(window.__h2ReleaseCalled, true, `${name}: release flag not set`)
  assert.equal(original?.message, 'DOM assertion failed')
  if (mode === 'cleanup-throws') {
    assert.equal(cleanupError?.message, 'cleanup boom')
  } else {
    assert.equal(cleanupError, null)
  }

  // Cleanup is idempotent: a second run must not call the real fetch again.
  try {
    eval(cleanupJs)
  } catch (error) {
    if (mode !== 'cleanup-throws') throw error
  }
  assert.equal(realCalls, 1, `${name}: second cleanup re-ran the real fetch`)
  assert.equal(window.fetch, window.__h2RealFetch)

  return {
    name,
    settled: !settled.timedOut,
    calls: realCalls,
    released: window.__h2ReleaseCalled === true,
    fetchRestored: window.fetch === window.__h2RealFetch,
    originalError: original?.message ?? null,
    cleanupError: cleanupError?.message ?? null,
  }
}

const results = [
  await runCase('ordinary', 'ordinary'),
  await runCase('fallback', 'fallback'),
  await runCase('cleanup-throws', 'cleanup-throws'),
]
console.log(JSON.stringify({ ok: true, results }))
