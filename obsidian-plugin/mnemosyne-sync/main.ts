import { spawn } from "node:child_process";
import {
  App,
  Notice,
  Plugin,
  PluginSettingTab,
  Setting,
  TFile,
  normalizePath
} from "obsidian";
import { DebouncedSyncQueue } from "./sync_queue";

interface MnemosyneSettings {
  cliPath: string;
  dbPath: string;
  rawRoot: string;
  wikiRoot: string;
  scopeId: string;
  autoSync: boolean;
  debounceMs: number;
}

interface SyncSummary {
  total?: number;
  changed?: number;
  new_files?: number;
  unchanged?: number;
  errors?: number;
}

const DEFAULT_SETTINGS: MnemosyneSettings = {
  cliPath: "mnemosyne",
  dbPath: "",
  rawRoot: "",
  wikiRoot: "_MnemosyneWiki",
  scopeId: "personal",
  autoSync: false,
  debounceMs: 1000
};

export default class MnemosyneSyncPlugin extends Plugin {
  settings: MnemosyneSettings = { ...DEFAULT_SETTINGS };
  private syncQueue!: DebouncedSyncQueue;
  private lastSummary: SyncSummary | undefined;

  async onload(): Promise<void> {
    await this.loadSettings();
    this.syncQueue = new DebouncedSyncQueue(
      this.settings.debounceMs,
      () => this.executeVaultSync(false)
    );
    this.addSettingTab(new MnemosyneSettingTab(this.app, this));
    this.addCommand({
      id: "sync-current-note",
      name: "Sync current note",
      callback: () => void this.syncCurrentNote(false)
    });
    this.addCommand({
      id: "dry-run-current-note",
      name: "Dry-run current note",
      callback: () => void this.syncCurrentNote(true)
    });
    this.addCommand({
      id: "sync-vault",
      name: "Sync vault",
      callback: () => void this.syncVault(false)
    });
    this.addCommand({
      id: "show-last-sync",
      name: "Show last Mnemosyne sync",
      callback: () => this.showLastSync()
    });
    this.addCommand({
      id: "open-generated-wiki",
      name: "Open generated Mnemosyne Wiki",
      callback: () => void this.openGeneratedWiki()
    });

    this.registerEvent(
      this.app.vault.on("modify", (file) => {
        if (!(file instanceof TFile) || !this.settings.autoSync || !this.shouldSync(file.path)) {
          return;
        }
        this.syncQueue.enqueue(file.path);
      })
    );
  }

  onunload(): void {
    this.syncQueue.dispose();
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  async updateDebounceMs(value: number): Promise<void> {
    this.settings.debounceMs = Math.max(100, value);
    this.syncQueue.setDelay(this.settings.debounceMs);
    await this.saveSettings();
  }

  private async loadSettings(): Promise<void> {
    const stored = (await this.loadData()) as Partial<MnemosyneSettings> | null;
    this.settings = { ...DEFAULT_SETTINGS, ...(stored ?? {}) };
  }

  private async syncCurrentNote(dryRun: boolean): Promise<void> {
    const file = this.app.workspace.getActiveFile();
    if (!file) {
      new Notice("Mnemosyne: no active note");
      return;
    }
    if (!this.shouldSync(file.path)) {
      new Notice("Mnemosyne: this note is excluded from sync");
      return;
    }

    try {
      await this.syncQueue.runNow(() => this.executeSync(
        dryRun ? "Dry-run current note" : "Current note sync",
        [...this.commonArgs(dryRun), "--file", this.fullPath(file.path)]
      ));
    } catch {
      new Notice("Mnemosyne: configure the CLI, DB path, and raw root first");
    }
  }

  private async syncVault(dryRun: boolean): Promise<void> {
    try {
      await this.syncQueue.runNow(() => this.executeVaultSync(dryRun));
    } catch {
      new Notice("Mnemosyne: configure the CLI, DB path, and raw root first");
    }
  }

  private async executeVaultSync(dryRun: boolean): Promise<void> {
    try {
      await this.executeSync(
        dryRun ? "Dry-run vault" : "Vault sync",
        this.commonArgs(dryRun)
      );
    } catch {
      new Notice("Mnemosyne: configure the CLI, DB path, and raw root first");
    }
  }

  private async executeSync(label: string, args: string[]): Promise<void> {
    const summary = await this.runCli(args);
    this.lastSummary = summary;
    new Notice(`${label}: ${formatSummary(summary)}`);
  }
  private runCli(args: string[]): Promise<SyncSummary> {
    this.validateSettings();
    const { promise, resolve, reject } = Promise.withResolvers<SyncSummary>();
    const child = spawn(this.settings.cliPath, args, {
      shell: false,
      windowsHide: true
    });
    let stdout = "";
    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", () => undefined);
    child.once("error", () => reject(new Error("mnemosyne CLI could not start")));
    child.once("close", (code) => {
      if (code !== 0) {
        reject(new Error("mnemosyne CLI failed"));
        return;
      }
      const summary = parseSummary(stdout);
      if (!summary) {
        reject(new Error("mnemosyne CLI returned no JSON summary"));
        return;
      }
      resolve(summary);
    });
    return promise;
  }
  private commonArgs(dryRun: boolean): string[] {
    const args = [
      "sync",
      "obsidian",
      this.vaultRoot(),
      "--db-path",
      this.settings.dbPath,
      "--raw-root",
      this.settings.rawRoot,
      "--wiki-root",
      this.fullPath(this.settings.wikiRoot),
      "--scope-id",
      this.settings.scopeId,
      "--source-channel",
      "obsidian"
    ];
    if (dryRun) {
      args.push("--dry-run");
    }
    return args;
  }

  private validateSettings(): void {
    if (!this.settings.cliPath.trim() || !this.settings.dbPath.trim() || !this.settings.rawRoot.trim()) {
      throw new Error("Mnemosyne CLI, DB path, and raw root are required");
    }
  }

  private shouldSync(path: string): boolean {
    const normalized = normalizePath(path).replace(/^\/+/, "");
    const wiki = normalizePath(this.settings.wikiRoot).replace(/^\/+|\/+$/g, "");
    return ![
      ".obsidian/",
      ".trash/",
      `${wiki}/`
    ].some((prefix) => normalized === prefix.slice(0, -1) || normalized.startsWith(prefix));
  }

  private vaultRoot(): string {
    const adapter = this.app.vault.adapter as unknown as { getBasePath?: () => string };
    const basePath = adapter.getBasePath?.();
    if (!basePath) {
      throw new Error("Obsidian vault base path is unavailable");
    }
    return basePath;
  }

  private fullPath(path: string): string {
    const adapter = this.app.vault.adapter as unknown as { getFullPath?: (value: string) => string };
    const fullPath = adapter.getFullPath?.(path);
    if (fullPath) {
      return fullPath;
    }
    return path;
  }

  private showLastSync(): void {
    if (!this.lastSummary) {
      new Notice("Mnemosyne: no sync has completed in this session");
      return;
    }
    new Notice(`Mnemosyne: ${formatSummary(this.lastSummary)}`);
  }

  private async openGeneratedWiki(): Promise<void> {
    const wikiIndex = normalizePath(`${this.settings.wikiRoot}/index.md`);
    await this.app.workspace.openLinkText(wikiIndex, "", true);
  }
}

class MnemosyneSettingTab extends PluginSettingTab {
  constructor(app: App, private readonly plugin: MnemosyneSyncPlugin) {
    super(app, plugin);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Mnemosyne Sync" });

    textSetting(containerEl, "Mnemosyne CLI path", "Executable used by the desktop plugin", this.plugin.settings.cliPath, async (value) => {
      this.plugin.settings.cliPath = value.trim();
      await this.plugin.saveSettings();
    });
    textSetting(containerEl, "KnowledgeGraph DB path", "Must be outside the Obsidian vault", this.plugin.settings.dbPath, async (value) => {
      this.plugin.settings.dbPath = value.trim();
      await this.plugin.saveSettings();
    });
    textSetting(containerEl, "Raw root", "Must be outside the Obsidian vault", this.plugin.settings.rawRoot, async (value) => {
      this.plugin.settings.rawRoot = value.trim();
      await this.plugin.saveSettings();
    });
    textSetting(containerEl, "Generated Wiki path", "Vault-relative path, normally _MnemosyneWiki", this.plugin.settings.wikiRoot, async (value) => {
      this.plugin.settings.wikiRoot = value.trim() || DEFAULT_SETTINGS.wikiRoot;
      await this.plugin.saveSettings();
    });
    textSetting(containerEl, "Scope ID", "Default personal", this.plugin.settings.scopeId, async (value) => {
      this.plugin.settings.scopeId = value.trim() || DEFAULT_SETTINGS.scopeId;
      await this.plugin.saveSettings();
    });

    new Setting(containerEl)
      .setName("Automatic sync on note changes")
      .setDesc("Runs a debounced hash-based Vault sync after a note is saved")
      .addToggle((toggle) => toggle
        .setValue(this.plugin.settings.autoSync)
        .onChange(async (value) => {
          this.plugin.settings.autoSync = value;
          await this.plugin.saveSettings();
        }));

    new Setting(containerEl)
      .setName("Debounce interval (ms)")
      .setDesc("Minimum delay before automatic sync")
      .addText((text) => text
        .setValue(String(this.plugin.settings.debounceMs))
        .onChange(async (value) => {
          const parsed = Number.parseInt(value, 10);
          if (Number.isFinite(parsed)) {
            await this.plugin.updateDebounceMs(parsed);
          }
        }));
  }
}

function textSetting(
  container: HTMLElement,
  name: string,
  description: string,
  value: string,
  onChange: (value: string) => Promise<void>
): void {
  new Setting(container)
    .setName(name)
    .setDesc(description)
    .addText((text) => text.setValue(value).onChange(onChange));
}

function parseSummary(stdout: string): SyncSummary | undefined {
  const lines = stdout.trim().split(/\r?\n/).reverse();
  for (const line of lines) {
    try {
      const parsed: unknown = JSON.parse(line);
      if (parsed !== null && typeof parsed === "object") {
        return parsed as SyncSummary;
      }
    } catch {
      // CLI diagnostics before the final JSON line are ignored.
    }
  }
  return undefined;
}

function formatSummary(summary: SyncSummary): string {
  const total = summary.total ?? 0;
  const changed = summary.changed ?? 0;
  const added = summary.new_files ?? 0;
  const unchanged = summary.unchanged ?? 0;
  const errors = summary.errors ?? 0;
  return `${total} scanned, ${changed + added} updated, ${unchanged} unchanged, ${errors} errors`;
}
