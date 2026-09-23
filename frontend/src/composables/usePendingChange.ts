import { ref } from 'vue'
import * as api from '../api'
import type { ConfigurationChange } from '../types'

/**
 * Pending-preview recovery.
 *
 * Only the non-authoritative preview id is kept in sessionStorage; after a
 * refresh or an unclear network result we recover state with
 * GET /configuration-changes/{id}. We never blindly re-send apply or build a
 * new candidate: the server row is the source of truth.
 */
const STORAGE_KEY = 'kg_pending_change_id'

const pending = ref<ConfigurationChange | null>(null)

function persistId(id: string | null) {
  try {
    if (id) sessionStorage.setItem(STORAGE_KEY, id)
    else sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // sessionStorage unavailable: in-memory state still works this session.
  }
}

export function rememberPending(change: ConfigurationChange) {
  pending.value = change
  persistId(change.id)
}

export function clearPending() {
  pending.value = null
  persistId(null)
}

export function getPending(): ConfigurationChange | null {
  return pending.value
}

export type RestoreOutcome =
  | { outcome: 'recovered'; change: ConfigurationChange }
  | { outcome: 'already_applied'; change: ConfigurationChange }
  | { outcome: 'unrecoverable' }

export async function restorePending(): Promise<RestoreOutcome | null> {
  let id: string | null = null
  try {
    id = sessionStorage.getItem(STORAGE_KEY)
  } catch {
    id = null
  }
  if (!id) return null

  try {
    const change = await api.getConfigurationChange(id)
    if (change.status === 'applied') {
      // Idempotent result: the change already landed. Drop the pointer and
      // let the caller show the result, never re-apply.
      persistId(null)
      pending.value = null
      return { outcome: 'already_applied', change }
    }
    if (change.status === 'pending') {
      pending.value = change
      return { outcome: 'recovered', change }
    }
    // Unknown/failed status: cannot safely reuse.
    persistId(null)
    return { outcome: 'unrecoverable' }
  } catch (err) {
    const e = err as api.ApiError
    if (e.status === 404) {
      persistId(null)
      return { outcome: 'unrecoverable' }
    }
    // Network/5xx: keep the id so a later retry can recover.
    throw err
  }
}
