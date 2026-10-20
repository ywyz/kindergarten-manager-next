/**
 * Node regression test for the D0 host-bridge readiness helpers (R6).
 *
 * Run with:  node frontend/src/d0/bridge.test.mjs
 *
 * Node strips the TypeScript types from ``bridge.ts``; the helpers take an
 * injectable clock/sleep so the "pywebview exists but the function is not
 * injected yet" gap is simulated deterministically.
 */
import assert from 'node:assert'
import {
  isSaveApiReady,
  isSessionApiReady,
  waitForSessionApi,
} from './bridge.ts'

function makeClock() {
  let t = 0
  return {
    now: () => t,
    async sleep(ms) {
      t += ms
    },
  }
}

// api object exists but the required function is not injected yet.
assert.equal(isSessionApiReady({ api: {} }), false)
assert.equal(isSessionApiReady({}), false)
assert.equal(isSessionApiReady(undefined), false)
assert.equal(isSessionApiReady(null), false)
assert.equal(isSessionApiReady({ api: { get_session: () => Promise.resolve({}) } }), true)
assert.equal(isSaveApiReady({ api: { get_session: () => Promise.resolve({}) } }), false)
assert.equal(isSaveApiReady({ api: { save_docx: () => Promise.resolve({}) } }), true)

// Already ready: resolves without sleeping.
{
  const clock = makeClock()
  const host = { api: { get_session: () => Promise.resolve({ launch_token: 'x' }) } }
  const result = await waitForSessionApi(() => host, { ...clock, timeoutMs: 1000, pollMs: 100 })
  assert.equal(result, 'ready')
  assert.equal(clock.now(), 0)
}

// Delayed injection: the api object appears first, the function later.
{
  const clock = makeClock()
  let host = { api: {} }
  let polls = 0
  const getHost = () => {
    polls += 1
    if (polls >= 4) host = { api: { get_session: () => Promise.resolve({}) } }
    return host
  }
  const result = await waitForSessionApi(getHost, { ...clock, timeoutMs: 1000, pollMs: 100 })
  assert.equal(result, 'ready')
  assert.ok(polls >= 4, `expected the function to be polled, got ${polls}`)
}

// Never injected: bounded timeout, not a fixed prolonged sleep.
{
  const clock = makeClock()
  const result = await waitForSessionApi(() => ({ api: {} }), {
    ...clock,
    timeoutMs: 1000,
    pollMs: 100,
  })
  assert.equal(result, 'timeout')
  assert.ok(clock.now() >= 1000)
}

console.log('OK bridge readiness regression tests')
