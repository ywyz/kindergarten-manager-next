/**
 * Theme state, DOM application and the single persisted theme controller.
 *
 * The backend appearance preference is the only cross-restart authority.
 * The controller keeps the latest explicit intent, coalesces writes to one
 * in-flight request per profile epoch, ignores late responses, and resets all
 * intent/queue on restore/profile/retire. Views must use the CSS tokens in
 * theme.css; this module deliberately never reads localStorage or the system
 * colour scheme.
 */

import { ref, type Ref } from 'vue'

export type ThemeMode = 'light' | 'dark'

export type ThemeStatus =
  | 'idle'
  | 'saving'
  | 'saved'
  | 'unsaved'
  | 'conflict'
  | 'unknown'

export interface AppearanceDTO {
  mode: ThemeMode
  version: number
}

export interface AppearancePatch {
  mode: ThemeMode
  expected_version: number
}

export interface AppearanceApi {
  get(): Promise<AppearanceDTO>
  patch(body: AppearancePatch): Promise<AppearanceDTO>
}

export type ThemeContext = 'uninitialized' | 'ready'

export interface ThemeInitializeInput {
  context: ThemeContext
  profileEpoch: number
}

export interface ThemeResetInput {
  reason: 'restore' | 'profile-replace' | 'retire'
  profileEpoch: number
}

export interface ThemeControllerDeps {
  api: AppearanceApi
  apply: (mode: ThemeMode) => void
  notify?: (status: ThemeStatus) => void
}

export interface ThemeController {
  mode: Ref<ThemeMode>
  version: Ref<number | null>
  status: Ref<ThemeStatus>
  initialize(input: ThemeInitializeInput): Promise<void>
  setMode(mode: ThemeMode): void
  retry(): Promise<void>
  reset(input: ThemeResetInput): void
  dispose(): void
}

function isMode(value: unknown): value is ThemeMode {
  return value === 'light' || value === 'dark'
}

function typeName(value: unknown): string {
  return Object.prototype.toString
    .call(value)
    .slice(8, -1)
    .toLowerCase()
}

function isVersion(value: unknown): value is number {
  return typeName(value) === 'number' && Number.isInteger(value as number) && (value as number) > 0
}

function validAppearance(value: unknown): AppearanceDTO {
  const candidate = value as Partial<AppearanceDTO> | null
  if (!candidate || !isMode(candidate.mode) || !isVersion(candidate.version)) {
    throw new Error('APPEARANCE_RESPONSE_INVALID')
  }
  return { mode: candidate.mode, version: candidate.version }
}

function statusForError(error: unknown): ThemeStatus {
  const err = error as { status?: unknown; code?: unknown } | null
  if (err?.status === 409 || err?.code === 'APPEARANCE_VERSION_CONFLICT') {
    return 'conflict'
  }
  if (err?.status === 0) return 'unknown'
  return 'unsaved'
}

/**
 * Apply the only DOM contract used by the app shell. All colour values live
 * in theme.css under :root/html.dark; this function only flips the class and
 * the native colour-scheme hint. It does not mount or key Vue.
 */
export function applyThemeMode(root: HTMLElement, mode: ThemeMode): void {
  root.classList.toggle('dark', mode === 'dark')
  root.style.colorScheme = mode
}


export function createThemeController(deps: ThemeControllerDeps): ThemeController {
  const mode = ref<ThemeMode>('light')
  const version = ref<number | null>(null)
  const status = ref<ThemeStatus>('idle')

  let context: ThemeContext = 'uninitialized'
  let epoch = 0
  let epochInitialized = false
  let explicitIntent: ThemeMode | null = null
  let persistedMode: ThemeMode | null = null
  let disposed = false
  let generation = 0
  let stateRev = 0
  let pumpPromise: Promise<void> | null = null
  let initializePromise: Promise<void> | null = null
  let initializeKey = ''
  let readPromise: Promise<AppearanceDTO | null> | null = null
  let readKey = ''
  let conflictRetryAvailable = true

  const setStatus = (next: ThemeStatus): void => {
    if (status.value === next) return
    status.value = next
    deps.notify?.(next)
  }

  const apply = (next: ThemeMode): void => {
    mode.value = next
    deps.apply(next)
  }

  const currentVersion = (): number | null => version.value

  const readAppearance = (
    expectedGeneration: number,
    expectedEpoch: number,
    expectedRev: number,
  ): Promise<AppearanceDTO | null> => {
    const key = `${expectedGeneration}:${expectedEpoch}:${expectedRev}`
    if (readPromise && readKey === key) return readPromise
    const promise = (async () => {
      let current: AppearanceDTO
      try {
        current = validAppearance(await deps.api.get())
      } catch {
        if (
          disposed ||
          expectedGeneration !== generation ||
          expectedEpoch !== epoch ||
          expectedRev !== stateRev
        ) return null
        setStatus('unknown')
        return null
      }
      if (
        disposed ||
        expectedGeneration !== generation ||
        expectedEpoch !== epoch ||
        expectedRev !== stateRev
      ) return null
      version.value = current.version
      persistedMode = current.mode
      stateRev += 1
      return current
    })()
    readPromise = promise
    readKey = key
    void promise.finally(() => {
      if (readPromise === promise) {
        readPromise = null
        readKey = ''
      }
    })
    return promise
  }

  const pump = (): Promise<void> => {
    if (pumpPromise) return pumpPromise
    const pumpGeneration = generation
    const pumpEpoch = epoch
    pumpPromise = (async () => {
      while (
        !disposed &&
        context === 'ready' &&
        explicitIntent !== null &&
        currentVersion() !== null &&
        explicitIntent !== persistedMode
      ) {
        const expectedGeneration = generation
        const expectedEpoch = epoch
        const target = explicitIntent
        const expectedVersion = currentVersion()
        if (expectedVersion === null) break
        setStatus('saving')
        try {
          const current = validAppearance(
            await deps.api.patch({ mode: target, expected_version: expectedVersion }),
          )
          if (
            disposed ||
            expectedGeneration !== generation ||
            expectedEpoch !== epoch ||
            (version.value !== null && current.version < version.value)
          ) return
          version.value = current.version
          persistedMode = current.mode
          stateRev += 1
          conflictRetryAvailable = true
          if (explicitIntent === target && persistedMode === target) {
            setStatus('saved')
          }
        } catch (error) {
          if (
            disposed ||
            expectedGeneration !== generation ||
            expectedEpoch !== epoch
          ) return
          if (statusForError(error) === 'conflict') {
            setStatus('conflict')
            const current = await readAppearance(generation, epoch, stateRev)
            if (!current) return
            if (explicitIntent === null) return
            if (persistedMode === explicitIntent) {
              setStatus('saved')
              return
            }
            if (conflictRetryAvailable) {
              conflictRetryAvailable = false
              continue
            }
            setStatus('conflict')
            return
          }
          const failure = statusForError(error)
          setStatus(failure)
          const current = await readAppearance(generation, epoch, stateRev)
          if (!current) return
          if (explicitIntent !== null && persistedMode === explicitIntent) {
            setStatus('saved')
          }
          return
        }
      }
      if (
        !disposed &&
        context === 'ready' &&
        explicitIntent !== null &&
        currentVersion() !== null &&
        explicitIntent === persistedMode
      ) {
        setStatus('saved')
      }
    })().finally(() => {
      if (pumpGeneration === generation && pumpEpoch === epoch) pumpPromise = null
    })
    return pumpPromise
  }

  const initialize = (input: ThemeInitializeInput): Promise<void> => {
    if (disposed) return Promise.resolve()
    if (input.profileEpoch !== epoch) {
      const discard =
        epochInitialized && (context === 'ready' || version.value !== null)
      if (discard) {
        generation += 1
        stateRev += 1
        explicitIntent = null
        persistedMode = null
        version.value = null
        pumpPromise = null
        initializePromise = null
        readPromise = null
        readKey = ''
        initializeKey = ''
        conflictRetryAvailable = true
        apply('light')
      }
      epoch = input.profileEpoch
      epochInitialized = true
    }
    epochInitialized = true
    context = input.context
    if (input.context === 'uninitialized') {
      // First page: window-only. A deliberate choice is retained for the
      // later ready transition; no persistence is claimed here.
      if (status.value === 'conflict' || status.value === 'unknown') setStatus('idle')
      return Promise.resolve()
    }
    if (version.value !== null) {
      // Repeated context updates for the same epoch must not reset the theme.
      if (explicitIntent !== null && explicitIntent !== persistedMode) {
        return pump()
      }
      return Promise.resolve()
    }
    const key = `${generation}:${epoch}:${context}`
    if (initializePromise && initializeKey === key) return initializePromise
    const promise = (async () => {
      const expectedGeneration = generation
      const expectedEpoch = epoch
      const current = await readAppearance(expectedGeneration, expectedEpoch, stateRev)
      if (!current || disposed || expectedGeneration !== generation) return
      if (explicitIntent === null) {
        explicitIntent = current.mode
        apply(current.mode)
        setStatus('saved')
        return
      }
      if (explicitIntent !== persistedMode) {
        await pump()
      } else {
        setStatus('saved')
      }
    })()
    initializePromise = promise
    initializeKey = key
    void promise.finally(() => {
      if (initializePromise === promise) {
        initializePromise = null
        initializeKey = ''
      }
    })
    return promise
  }

  const setMode = (next: ThemeMode): void => {
    if (disposed || !isMode(next)) return
    explicitIntent = next
    apply(next)
    conflictRetryAvailable = true
    if (context !== 'ready') {
      setStatus('idle')
      return
    }
    if (currentVersion() === null) {
      setStatus('unknown')
      return
    }
    if (persistedMode === next && !pumpPromise) {
      setStatus('saved')
      return
    }
    void pump()
  }

  const retry = async (): Promise<void> => {
    if (disposed || context !== 'ready') return
    const current = await readAppearance(generation, epoch, stateRev)
    if (!current || disposed) return
    if (explicitIntent === null) {
      explicitIntent = current.mode
      apply(current.mode)
      setStatus('saved')
      return
    }
    if (persistedMode === explicitIntent) {
      setStatus('saved')
      return
    }
    // A failure reconciliation may still own the old pump. Wait for that
    // pump to settle, then ensure this explicit retry gets one new write;
    // never rejoin the already-finished promise or silently drop retry.
    if (pumpPromise) await pumpPromise
    if (!disposed && context === 'ready' && explicitIntent !== persistedMode) {
      conflictRetryAvailable = true
      await pump()
    }
  }

  const reset = (input: ThemeResetInput): void => {
    if (disposed) return
    generation += 1
    stateRev += 1
    epoch = input.profileEpoch
    epochInitialized = true
    context = 'uninitialized'
    explicitIntent = null
    persistedMode = null
    version.value = null
    pumpPromise = null
    initializePromise = null
    readPromise = null
    readKey = ''
    initializeKey = ''
    conflictRetryAvailable = true
    apply('light')
    setStatus('idle')
  }

  const dispose = (): void => {
    disposed = true
    generation += 1
    stateRev += 1
    pumpPromise = null
    initializePromise = null
    readPromise = null
    explicitIntent = null
    persistedMode = null
  }

  return { mode, version, status, initialize, setMode, retry, reset, dispose }
}
