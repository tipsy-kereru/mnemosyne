var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// main.ts
var main_exports = {};
__export(main_exports, {
  default: () => MnemosyneSyncPlugin
});
module.exports = __toCommonJS(main_exports);
var import_node_child_process = require("node:child_process");
var import_obsidian = require("obsidian");

// sync_queue.ts
var REAL_TIMERS = {
  set: (callback, delayMs) => setTimeout(callback, delayMs),
  clear: (handle) => clearTimeout(handle)
};
var DebouncedSyncQueue = class {
  constructor(delayMs, run, timers = REAL_TIMERS) {
    this.run = run;
    this.timers = timers;
    this.pending = /* @__PURE__ */ new Set();
    this.running = false;
    this.rerunAfterCurrent = false;
    this.retryScheduled = false;
    this.delayMs = Math.max(100, delayMs);
  }
  enqueue(path) {
    this.pending.add(path);
    this.schedule();
  }
  setDelay(delayMs) {
    this.delayMs = Math.max(100, delayMs);
    if (this.pending.size > 0) {
      this.schedule();
    }
  }
  async runNow(task = this.run) {
    if (this.timer !== void 0) {
      this.timers.clear(this.timer);
      this.timer = void 0;
      this.retryScheduled = false;
    }
    this.pending.clear();
    if (this.running) {
      this.rerunAfterCurrent = true;
      return;
    }
    await this.start(task);
  }
  dispose() {
    if (this.timer !== void 0) {
      this.timers.clear(this.timer);
      this.timer = void 0;
    }
    this.pending.clear();
    this.rerunAfterCurrent = false;
    this.retryScheduled = false;
  }
  schedule() {
    if (this.timer !== void 0) {
      this.timers.clear(this.timer);
    }
    this.timer = this.timers.set(() => {
      this.timer = void 0;
      void this.flush();
    }, this.delayMs);
  }
  async flush() {
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
  async start(task) {
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
};

// main.ts
var DEFAULT_SETTINGS = {
  cliPath: "mnemosyne",
  dbPath: "",
  rawRoot: "",
  wikiRoot: "_MnemosyneWiki",
  scopeId: "personal",
  autoSync: false,
  debounceMs: 1e3
};
var MnemosyneSyncPlugin = class extends import_obsidian.Plugin {
  constructor() {
    super(...arguments);
    this.settings = { ...DEFAULT_SETTINGS };
  }
  async onload() {
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
        if (!(file instanceof import_obsidian.TFile) || !this.settings.autoSync || !this.shouldSync(file.path)) {
          return;
        }
        this.syncQueue.enqueue(file.path);
      })
    );
  }
  onunload() {
    this.syncQueue.dispose();
  }
  async saveSettings() {
    await this.saveData(this.settings);
  }
  async updateDebounceMs(value) {
    this.settings.debounceMs = Math.max(100, value);
    this.syncQueue.setDelay(this.settings.debounceMs);
    await this.saveSettings();
  }
  async loadSettings() {
    const stored = await this.loadData();
    this.settings = { ...DEFAULT_SETTINGS, ...stored ?? {} };
  }
  async syncCurrentNote(dryRun) {
    const file = this.app.workspace.getActiveFile();
    if (!file) {
      new import_obsidian.Notice("Mnemosyne: no active note");
      return;
    }
    if (!this.shouldSync(file.path)) {
      new import_obsidian.Notice("Mnemosyne: this note is excluded from sync");
      return;
    }
    try {
      await this.syncQueue.runNow(() => this.executeSync(
        dryRun ? "Dry-run current note" : "Current note sync",
        [...this.commonArgs(dryRun), "--file", this.fullPath(file.path)]
      ));
    } catch {
      new import_obsidian.Notice("Mnemosyne: configure the CLI, DB path, and raw root first");
    }
  }
  async syncVault(dryRun) {
    try {
      await this.syncQueue.runNow(() => this.executeVaultSync(dryRun));
    } catch {
      new import_obsidian.Notice("Mnemosyne: configure the CLI, DB path, and raw root first");
    }
  }
  async executeVaultSync(dryRun) {
    try {
      await this.executeSync(
        dryRun ? "Dry-run vault" : "Vault sync",
        this.commonArgs(dryRun)
      );
    } catch {
      new import_obsidian.Notice("Mnemosyne: configure the CLI, DB path, and raw root first");
    }
  }
  async executeSync(label, args) {
    const summary = await this.runCli(args);
    this.lastSummary = summary;
    new import_obsidian.Notice(`${label}: ${formatSummary(summary)}`);
  }
  runCli(args) {
    this.validateSettings();
    const { promise, resolve, reject } = Promise.withResolvers();
    const child = (0, import_node_child_process.spawn)(this.settings.cliPath, args, {
      shell: false,
      windowsHide: true
    });
    let stdout = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", () => void 0);
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
  commonArgs(dryRun) {
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
  validateSettings() {
    if (!this.settings.cliPath.trim() || !this.settings.dbPath.trim() || !this.settings.rawRoot.trim()) {
      throw new Error("Mnemosyne CLI, DB path, and raw root are required");
    }
  }
  shouldSync(path) {
    const normalized = (0, import_obsidian.normalizePath)(path).replace(/^\/+/, "");
    const wiki = (0, import_obsidian.normalizePath)(this.settings.wikiRoot).replace(/^\/+|\/+$/g, "");
    return ![
      ".obsidian/",
      ".trash/",
      `${wiki}/`
    ].some((prefix) => normalized === prefix.slice(0, -1) || normalized.startsWith(prefix));
  }
  vaultRoot() {
    const adapter = this.app.vault.adapter;
    const basePath = adapter.getBasePath?.();
    if (!basePath) {
      throw new Error("Obsidian vault base path is unavailable");
    }
    return basePath;
  }
  fullPath(path) {
    const adapter = this.app.vault.adapter;
    const fullPath = adapter.getFullPath?.(path);
    if (fullPath) {
      return fullPath;
    }
    return path;
  }
  showLastSync() {
    if (!this.lastSummary) {
      new import_obsidian.Notice("Mnemosyne: no sync has completed in this session");
      return;
    }
    new import_obsidian.Notice(`Mnemosyne: ${formatSummary(this.lastSummary)}`);
  }
  async openGeneratedWiki() {
    const wikiIndex = (0, import_obsidian.normalizePath)(`${this.settings.wikiRoot}/index.md`);
    await this.app.workspace.openLinkText(wikiIndex, "", true);
  }
};
var MnemosyneSettingTab = class extends import_obsidian.PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }
  display() {
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
    new import_obsidian.Setting(containerEl).setName("Automatic sync on note changes").setDesc("Runs a debounced hash-based Vault sync after a note is saved").addToggle((toggle) => toggle.setValue(this.plugin.settings.autoSync).onChange(async (value) => {
      this.plugin.settings.autoSync = value;
      await this.plugin.saveSettings();
    }));
    new import_obsidian.Setting(containerEl).setName("Debounce interval (ms)").setDesc("Minimum delay before automatic sync").addText((text) => text.setValue(String(this.plugin.settings.debounceMs)).onChange(async (value) => {
      const parsed = Number.parseInt(value, 10);
      if (Number.isFinite(parsed)) {
        await this.plugin.updateDebounceMs(parsed);
      }
    }));
  }
};
function textSetting(container, name, description, value, onChange) {
  new import_obsidian.Setting(container).setName(name).setDesc(description).addText((text) => text.setValue(value).onChange(onChange));
}
function parseSummary(stdout) {
  const lines = stdout.trim().split(/\r?\n/).reverse();
  for (const line of lines) {
    try {
      const parsed = JSON.parse(line);
      if (parsed !== null && typeof parsed === "object") {
        return parsed;
      }
    } catch {
    }
  }
  return void 0;
}
function formatSummary(summary) {
  const total = summary.total ?? 0;
  const changed = summary.changed ?? 0;
  const added = summary.new_files ?? 0;
  const unchanged = summary.unchanged ?? 0;
  const errors = summary.errors ?? 0;
  return `${total} scanned, ${changed + added} updated, ${unchanged} unchanged, ${errors} errors`;
}
