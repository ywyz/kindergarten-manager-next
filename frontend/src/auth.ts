import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import type { Account, Me } from './types'
import * as api from './api'

export interface AuthState {
  account: Account | null
  assignmentStatus: string
  canPrepare: boolean
  loading: boolean
  initialized: boolean
}

export const auth = reactive<AuthState>({
  account: null,
  assignmentStatus: '',
  canPrepare: false,
  loading: false,
  initialized: false,
})

export function isLoggedIn(): boolean {
  return auth.account !== null
}

export function isAdmin(): boolean {
  return auth.account?.role === 'admin'
}

export function isTeacher(): boolean {
  return auth.account?.role === 'teacher'
}

export async function restoreSession(): Promise<boolean> {
  auth.loading = true
  try {
    const me = await api.fetchMe()
    applyMe(me)
    return true
  } catch (err) {
    reset()
    return false
  } finally {
    auth.loading = false
    auth.initialized = true
  }
}

export async function doLogin(username: string, password: string): Promise<void> {
  auth.loading = true
  try {
    const me = await api.login({ username, password })
    applyMe(me)
  } finally {
    auth.loading = false
  }
}

export async function doLogout(): Promise<void> {
  try {
    await api.logout()
  } catch (err) {
    const e = err as api.ApiError
    // A 401 means the session is already invalid; clear state.
    if (e.status === 401) {
      reset()
      return
    }
    // Network or other errors must not pretend the logout succeeded.
    throw err
  }
  reset()
}

export function applyMe(me: Me): void {
  auth.account = me.account
  auth.assignmentStatus = me.assignment_status
  auth.canPrepare = me.can_prepare
}

export function reset(): void {
  auth.account = null
  auth.assignmentStatus = ''
  auth.canPrepare = false
}

export function expectedVersion(): number {
  return auth.account?.version ?? 1
}

export function handleApiError(err: unknown, fallback: string): void {
  const e = err as { status?: number; code?: string; message?: string; fields?: Record<string, string> }
  if (e.code === 'AUTH_REQUIRED') {
    // Global 401 handler already resets state and redirects.
    return
  }
  if (e.code === 'FORBIDDEN' || e.status === 403) {
    ElMessage.error(e.message || '没有权限执行此操作')
    return
  }
  ElMessage.error(e.message || fallback)
}
