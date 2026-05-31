/*
 * Status Indicator for SPEC-JOPLIN-004
 *
 * Simple sync status indicator:
 * - Green dot: connected to mnemosyne
 * - Yellow dot: syncing
 * - Red dot: unavailable
 * - Entity count badge: "N entities"
 *
 * Can be attached to a plugin panel or status bar.
 */

import { SyncStatus } from './sync_pipeline';

const STATUS_COLORS: Record<SyncStatus, string> = {
  connected: '#4CAF50',
  syncing: '#FFC107',
  unavailable: '#F44336',
};

const STATUS_LABELS: Record<SyncStatus, string> = {
  connected: 'mnemosyne connected',
  syncing: 'syncing...',
  unavailable: 'mnemosyne unavailable',
};

/**
 * Create a status indicator element.
 * Returns an HTML string suitable for embedding in a panel.
 */
export function createStatusIndicatorHtml(
  status: SyncStatus,
  entityCount: number,
): string {
  const color = STATUS_COLORS[status] || STATUS_COLORS.unavailable;
  const label = STATUS_LABELS[status] || 'unknown';

  return `<div id="kg-sync-status" style="display:flex;align-items:center;gap:8px;font-family:sans-serif;font-size:12px;color:#ccc;">
  <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block;" id="kg-sync-dot"></span>
  <span id="kg-sync-label">${label}</span>
  <span style="background:#0f3460;color:#aaa;padding:1px 6px;border-radius:8px;font-size:10px;" id="kg-entity-count">${entityCount} entities</span>
</div>`;
}

/**
 * Update an existing status indicator in the DOM.
 * Safe to call when the indicator may not be mounted yet.
 */
export function updateStatusIndicator(
  container: HTMLElement,
  status: SyncStatus,
  entityCount: number,
): void {
  const dot = container.querySelector('#kg-sync-dot') as HTMLElement | null;
  const label = container.querySelector('#kg-sync-label') as HTMLElement | null;
  const count = container.querySelector('#kg-entity-count') as HTMLElement | null;

  if (dot) {
    dot.style.background = STATUS_COLORS[status] || STATUS_COLORS.unavailable;
  }
  if (label) {
    label.textContent = STATUS_LABELS[status] || 'unknown';
  }
  if (count) {
    count.textContent = `${entityCount} entities`;
  }
}

/**
 * Create a standalone status indicator element (for programmatic use).
 */
export function createStatusIndicatorElement(
  status: SyncStatus,
  entityCount: number,
): HTMLElement {
  const wrapper = document.createElement('div');
  wrapper.id = 'kg-sync-status';
  wrapper.style.cssText = 'display:flex;align-items:center;gap:8px;font-family:sans-serif;font-size:12px;color:#ccc;';

  const dot = document.createElement('span');
  dot.id = 'kg-sync-dot';
  dot.style.cssText = `width:8px;height:8px;border-radius:50%;background:${STATUS_COLORS[status]};display:inline-block;`;
  wrapper.appendChild(dot);

  const label = document.createElement('span');
  label.id = 'kg-sync-label';
  label.textContent = STATUS_LABELS[status];
  wrapper.appendChild(label);

  const badge = document.createElement('span');
  badge.id = 'kg-entity-count';
  badge.style.cssText = 'background:#0f3460;color:#aaa;padding:1px 6px;border-radius:8px;font-size:10px;';
  badge.textContent = `${entityCount} entities`;
  wrapper.appendChild(badge);

  return wrapper;
}
