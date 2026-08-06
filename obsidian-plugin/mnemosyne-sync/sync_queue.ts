export interface SyncQueueTimer {
  set(callback: () => void, delayMs: number): unknown;
  clear(handle: unknown): void;
}

const REAL_TIMERS: SyncQueueTimer = {
  set: (callback, delayMs) => setTimeout(callback, delayMs),
  clear: (handle) => clearTimeout(handle as NodeJS.Timeout)
};

export class DebouncedSyncQueue {
  private delayMs: number;
  private timer: unknown;
  private pending = new Set<string>();
  private running = false;
  private rerunAfterCurrent = false;
  private retryScheduled = false;

  constructor(
    delayMs: number,
    private readonly run: () => Promise<void>,
    private readonly timers: SyncQueueTimer = REAL_TIMERS
  ) {
    this.delayMs = Math.max(100, delayMs);
  }

  enqueue(path: string): void {
    this.pending.add(path);
    this.schedule();
  }

  setDelay(delayMs: number): void {
    this.delayMs = Math.max(100, delayMs);
    if (this.pending.size > 0) {
      this.schedule();
    }
  }

  async runNow(task: () => Promise<void> = this.run): Promise<void> {
    if (this.timer !== undefined) {
      this.timers.clear(this.timer);
      this.timer = undefined;
      this.retryScheduled = false;
    }
    this.pending.clear();
    if (this.running) {
      this.rerunAfterCurrent = true;
      return;
    }
    await this.start(task);
  }

  dispose(): void {
    if (this.timer !== undefined) {
      this.timers.clear(this.timer);
      this.timer = undefined;
    }
    this.pending.clear();
    this.rerunAfterCurrent = false;
    this.retryScheduled = false;
  }

  private schedule(): void {
    if (this.timer !== undefined) {
      this.timers.clear(this.timer);
    }
    this.timer = this.timers.set(() => {
      this.timer = undefined;
      void this.flush();
    }, this.delayMs);
  }

  private async flush(): Promise<void> {
    if (this.pending.size === 0 && !this.rerunAfterCurrent && !this.retryScheduled) {
      return;
    }
    this.pending.clear();
    this.retryScheduled = false;
    if (this.running) {
      this.rerunAfterCurrent = true;
      return;
    }
    this.rerunAfterCurrent = false;
    await this.start(this.run);
  }

  private async start(task: () => Promise<void>): Promise<void> {
    this.running = true;
    try {
      await task();
    } finally {
      this.running = false;
      if (this.pending.size > 0 || this.rerunAfterCurrent) {
        this.rerunAfterCurrent = false;
        this.retryScheduled = true;
        this.schedule();
      }
    }
  }
}
