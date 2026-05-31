/*
 * Mnemosyne Server Process Manager
 *
 * SPEC-JOPLIN-002 REQ-S2-001
 * Manages the lifecycle of `mnemosyne serve` as a child process.
 * Uses child_process.spawn. No external dependencies.
 */

import { spawn, ChildProcess } from 'child_process';

// @MX:ANCHOR: [AUTO] Manages mnemosyne serve subprocess lifecycle for the plugin
// @MX:REASON: Called from index.ts initialize/shutdown and health check loop — fan_in >= 3
export class ServerManager {
  private process: ChildProcess | null = null;
  private dbPath: string;
  private port: number;
  private healthUrl: string;
  private restartAttempts: number = 0;
  private readonly maxRestartAttempts: number = 3;
  private restartTimer: ReturnType<typeof setTimeout> | null = null;
  private shuttingDown: boolean = false;

  constructor(dbPath: string = '', port: number = 57832) {
    this.dbPath = dbPath;
    this.port = port;
    this.healthUrl = `http://127.0.0.1:${port}/api/v1/health`;
  }

  async start(): Promise<boolean> {
    if (this.process && !this.process.killed) {
      // Already running — check health
      const healthy = await this.isRunning();
      if (healthy) return true;
      // Process exists but unhealthy — stop it first
      this.stop();
    }

    return this.spawnProcess();
  }

  stop(): void {
    this.shuttingDown = true;

    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }

    if (this.process && !this.process.killed) {
      this.process.kill('SIGTERM');
      this.process = null;
    }

    this.restartAttempts = 0;
  }

  async isRunning(): Promise<boolean> {
    try {
      const response = await fetch(this.healthUrl, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  getProcess(): ChildProcess | null {
    return this.process;
  }

  // Update configuration (used when settings change)
  updateConfig(dbPath: string, port: number): void {
    this.dbPath = dbPath;
    this.port = port;
    this.healthUrl = `http://127.0.0.1:${port}/api/v1/health`;
  }

  // --- Internal ---

  private spawnProcess(): Promise<boolean> {
    return new Promise((resolve) => {
      const args: string[] = ['serve'];

      if (this.dbPath) {
        args.push('--db', this.dbPath);
      }
      args.push('--port', String(this.port));

      try {
        this.process = spawn('mnemosyne', args, {
          stdio: ['ignore', 'pipe', 'pipe'],
          detached: false,
        });
      } catch (error: any) {
        console.error('Failed to spawn mnemosyne serve:', error?.message || error);
        resolve(false);
        return;
      }

      this.process.on('error', (err: Error) => {
        console.error('mnemosyne serve process error:', err.message);
        this.process = null;
        resolve(false);
      });

      // Log stderr for debugging
      if (this.process.stderr) {
        this.process.stderr.on('data', (data: Buffer) => {
          console.debug('mnemosyne serve:', data.toString().trim());
        });
      }

      // Handle unexpected exit with auto-restart
      this.process.on('exit', (code: number | null) => {
        console.warn(`mnemosyne serve exited with code ${code}`);
        this.process = null;

        if (!this.shuttingDown && this.restartAttempts < this.maxRestartAttempts) {
          this.scheduleRestart();
        }
      });

      // Wait briefly then check if process is alive and healthy
      // Give the server time to bind to port
      setTimeout(async () => {
        if (!this.process || this.process.killed) {
          resolve(false);
          return;
        }
        const healthy = await this.isRunning();
        resolve(healthy);
      }, 1500);
    });
  }

  // @MX:WARN: [AUTO] Exponential backoff restart — restartAttempts drives delay calculation
  // @MX:REASON: Prevents rapid crash loops when mnemosyne binary is broken; max 3 attempts caps total delay
  private scheduleRestart(): void {
    this.restartAttempts++;
    // Exponential backoff: 1s, 2s, 4s
    const delay = Math.pow(2, this.restartAttempts - 1) * 1000;

    console.warn(
      `Scheduling mnemosyne serve restart attempt ${this.restartAttempts}/${this.maxRestartAttempts} in ${delay}ms`,
    );

    this.restartTimer = setTimeout(async () => {
      this.restartTimer = null;
      const success = await this.spawnProcess();
      if (success) {
        console.log('mnemosyne serve restarted successfully');
        this.restartAttempts = 0;
      } else if (this.restartAttempts < this.maxRestartAttempts) {
        this.scheduleRestart();
      } else {
        console.error('Max restart attempts reached. mnemosyne serve is unavailable.');
      }
    }, delay);
  }
}
