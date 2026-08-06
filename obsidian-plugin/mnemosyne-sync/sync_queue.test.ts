import assert from "node:assert/strict";
import test from "node:test";
import { DebouncedSyncQueue, SyncQueueTimer } from "./sync_queue";

class FakeTimers implements SyncQueueTimer {
  private now = 0;
  private nextId = 0;
  private readonly timers = new Map<number, { at: number; callback: () => void }>();

  set(callback: () => void, delayMs: number): number {
    const id = this.nextId++;
    this.timers.set(id, { at: this.now + delayMs, callback });
    return id;
  }

  clear(handle: unknown): void {
    this.timers.delete(handle as number);
  }

  advance(milliseconds: number): void {
    this.now += milliseconds;
    while (true) {
      const due = [...this.timers.entries()]
        .filter(([, timer]) => timer.at <= this.now)
        .sort(([, left], [, right]) => left.at - right.at);
      if (due.length === 0) {
        return;
      }
      for (const [id, timer] of due) {
        this.timers.delete(id);
        timer.callback();
      }
    }
  }
}

async function flushMicrotasks(): Promise<void> {
  for (let index = 0; index < 5; index += 1) {
    await Promise.resolve();
  }
}

test("coalesces repeated note modifications into one sync", async () => {
  let runs = 0;
  const timers = new FakeTimers();
  const queue = new DebouncedSyncQueue(100, async () => {
    runs += 1;
  }, timers);

  queue.enqueue("Notes/a.md");
  queue.enqueue("Notes/a.md");
  queue.enqueue("Notes/b.md");
  timers.advance(100);
  await flushMicrotasks();
  queue.dispose();

  assert.equal(runs, 1);
});

test("schedules one follow-up sync when a modification arrives during sync", async () => {
  let runs = 0;
  const firstRun = Promise.withResolvers<void>();
  const started = Promise.withResolvers<void>();
  const timers = new FakeTimers();
  const queue = new DebouncedSyncQueue(100, async () => {
    runs += 1;
    if (runs === 1) {
      started.resolve();
      await firstRun.promise;
    }
  }, timers);

  queue.enqueue("Notes/a.md");
  timers.advance(100);
  await started.promise;
  queue.enqueue("Notes/a.md");
  timers.advance(100);
  firstRun.resolve();
  await flushMicrotasks();
  timers.advance(100);
  await flushMicrotasks();
  queue.dispose();

  assert.equal(runs, 2);
});
