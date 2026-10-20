/**
 * Unified leave coordinator (D1 spec §11.3).
 *
 * One ``requestLeave(action)`` manages closing the window, switching date /
 * term, returning to the calendar and entering settings. While a save is in
 * flight, the same target shares one promise, a different target is refused
 * (never queued or replaced), and a failure / conflict / new input keeps the
 * page. Only when the coordinator confirms the editor is still clean after
 * the save does the original action run.
 */

export type SaveOutcome =
  | 'unchanged'
  | 'saved'
  | 'failed'
  | 'conflict'
  | 'indeterminate'

export type LeaveKind = 'close' | 'date' | 'term' | 'calendar' | 'settings'

export interface LeaveAction {
  kind: LeaveKind
  /** For close actions: the host-issued close request id. */
  closeRequestId?: string
  /** Runs only after the leave is confirmed (navigation / close ack). */
  run: () => Promise<LeaveOutcome> | LeaveOutcome
}

export type LeaveOutcome = 'left' | 'stayed' | 'busy'

export interface LeaveEditor {
  /** True when the editor has unsaved input relative to its baseline. */
  isDirty: () => boolean
  /** planId + editEpoch; must be unchanged after a save for the leave to run. */
  identity: () => string
  /**
   * Wait until an active IME composition received its final input and the
   * Vue model update settled. The leave decision (dirty check) must happen
   * after this, otherwise a clean-looking page could still be composing the
   * user's last characters (R15).
   */
  settle?: () => Promise<void>
  /** Single in-flight save for the editor; shared by manual and leaving. */
  saveCurrent: () => Promise<SaveOutcome>
  /**
   * D2 W5: a candidate preview edit or settings draft that must be resolved
   * (adopt-and-save, or an explicit cancel restoring the reviewed value)
   * before the page may leave. Returns the blocking descriptor, or null when
   * nothing blocks leaving. Checked after the body save (spec §5.4 order:
   * settle → body save → candidate/settings draft check → close handshake).
   */
  blockingDraft?: () => BlockingDraft | null
}

export interface BlockingDraft {
  kind: 'candidate' | 'settings'
  message: string
}

export interface LeaveHooks {
  /** Called when the coordinator starts/finishes saving for a leave. */
  onStateChange?: (state: 'idle' | 'saving_for_leave') => void
  /** Human-readable reason for a failed leave (used by the UI). */
  describeFailure?: (outcome: SaveOutcome) => string
  onFailure?: (message: string) => void
}

interface ActiveLeave {
  key: string
  /**
   * Set by an authoritative close cancel (``cancelClose``): the run may keep
   * awaiting its in-flight save, but it must never execute its action,
   * clear a newer active leave or freeze again once it resumes.
   */
  cancelled: boolean
  promise: Promise<LeaveOutcome>
}

function actionKey(action: Pick<LeaveAction, 'kind' | 'closeRequestId'>): string {
  if (action.kind === 'close') {
    return `close:${action.closeRequestId ?? 'current'}`
  }
  return action.kind
}

export class LeaveCoordinator {
  private editor: LeaveEditor
  private hooks: LeaveHooks
  private active: ActiveLeave | null = null
  private state: 'idle' | 'saving_for_leave' = 'idle'

  constructor(editor: LeaveEditor, hooks: LeaveHooks = {}) {
    this.editor = editor
    this.hooks = hooks
  }

  isBusy(): boolean {
    return this.active !== null
  }

  getState(): 'idle' | 'saving_for_leave' {
    return this.state
  }

  /**
   * Request one leave. Clean editors run the action immediately; dirty ones
   * save first. Repeated requests for the same target share the in-flight
   * promise; a different target while busy is refused.
   */
  requestLeave(action: LeaveAction): Promise<LeaveOutcome> {
    const key = actionKey(action)
    if (this.active) {
      if (this.active.key === key) return this.active.promise
      return Promise.resolve('busy')
    }
    const entry: ActiveLeave = {
      key,
      cancelled: false,
      promise: Promise.resolve('stayed'),
    }
    this.active = entry
    entry.promise = this.run(action, entry)
    const clear = () => {
      // Only the exact entry may clear itself: a late cancelled run must
      // never clear a newer active leave (R1).
      if (this.active === entry) this.active = null
    }
    void entry.promise.then(clear, clear)
    return entry.promise
  }

  /**
   * Authoritative cancel for one close request id (the host's
   * ``close_aborted`` notification, spec §11.3): releases the coordinator
   * wait bound to that id so new navigation / close attempts are not blocked
   * by a bridge promise that may never answer. The in-flight save is not
   * discarded: the cancelled run keeps awaiting it and only then returns.
   * It never executes its action, never clears a newer active leave and
   * never freezes again.
   */
  cancelClose(closeRequestId: string): boolean {
    const entry = this.active
    if (!entry || entry.key !== actionKey({ kind: 'close', closeRequestId })) {
      return false
    }
    entry.cancelled = true
    this.active = null
    return true
  }

  private async run(action: LeaveAction, entry: ActiveLeave): Promise<LeaveOutcome> {
    if (entry.cancelled) return 'stayed'
    // A clean-looking editor may still have an active composition whose
    // final text has not reached the model yet: settle it before the dirty
    // decision so the last input is either saved or seen as dirty (R15).
    if (this.editor.settle) {
      try {
        await this.editor.settle()
      } catch {
        return 'stayed'
      }
    }
    if (entry.cancelled) return 'stayed'
    const blockedBefore = this.editor.blockingDraft?.() ?? null
    if (!this.editor.isDirty()) {
      // Body is clean: only a blocking candidate/settings draft keeps the page.
      if (blockedBefore) return this.stayForDraft(blockedBefore)
      return this.execute(action, entry)
    }
    this.state = 'saving_for_leave'
    this.hooks.onStateChange?.(this.state)
    const identityBefore = this.editor.identity()
    let outcome: SaveOutcome
    try {
      outcome = await this.editor.saveCurrent()
    } catch {
      outcome = 'failed'
    } finally {
      this.state = 'idle'
      this.hooks.onStateChange?.(this.state)
    }
    if (entry.cancelled) {
      // The close was authoritatively cancelled while the save was in
      // flight. The save result still belongs to the editor (never
      // discarded), but the cancelled leave executes nothing.
      return 'stayed'
    }
    if (outcome !== 'saved' && outcome !== 'unchanged') {
      this.hooks.onFailure?.(
        this.hooks.describeFailure?.(outcome) ?? '保存未完成，未离开当前页面',
      )
      return 'stayed'
    }
    // Re-check: a new input, a changed document or a differing identity means
    // the save no longer covers what would be left behind.
    if (this.editor.isDirty() || this.editor.identity() !== identityBefore) {
      this.hooks.onFailure?.(
        this.hooks.describeFailure?.('saved') ?? '页面仍有未保存的输入，未离开',
      )
      return 'stayed'
    }
    // The body was saved (or unchanged); a candidate/settings draft created or
    // still present now keeps the page (spec §5.4 ordering).
    const blockedAfter = this.editor.blockingDraft?.() ?? null
    if (blockedAfter) return this.stayForDraft(blockedAfter)
    return this.execute(action, entry)
  }

  private stayForDraft(draft: BlockingDraft): LeaveOutcome {
    this.hooks.onFailure?.(draft.message)
    return 'stayed'
  }

  private async execute(action: LeaveAction, entry: ActiveLeave): Promise<LeaveOutcome> {
    if (entry.cancelled) return 'stayed'
    try {
      const result = await action.run()
      if (entry.cancelled) return 'stayed'
      return result === undefined ? 'left' : result
    } catch {
      return 'stayed'
    }
  }
}
