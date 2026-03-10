interface UpdateProgressInfo {
  percent: number;
  bytesPerSecond: number;
  transferred: number;
  total: number;
}

interface UpdateVersionInfo {
  version: string;
}

interface AugustusUpdates {
  checkForUpdate(): Promise<void>;
  downloadUpdate(): Promise<void>;
  installUpdate(): Promise<void>;
  onUpdateAvailable(cb: (info: UpdateVersionInfo) => void): void;
  onUpdateNotAvailable(cb: () => void): void;
  onDownloadProgress(cb: (progress: UpdateProgressInfo) => void): void;
  onUpdateDownloaded(cb: () => void): void;
  onUpdateError(cb: (err: string) => void): void;
  removeAllListeners(): void;
}

interface ClaudeExtensionStatus {
  installed: boolean;
  enabled: boolean;
  claudeDesktopFound: boolean;
}

interface ClaudeExtensionResult {
  success: boolean;
  error?: string;
}

interface AugustusClaudeExtension {
  check(): Promise<ClaudeExtensionStatus>;
  install(dataDir: string): Promise<ClaudeExtensionResult>;
  uninstall(): Promise<ClaudeExtensionResult>;
}

interface AugustusAPI {
  platform: string;
  version: string;
  isElectron: boolean;
  getDataDir(): Promise<string>;
  getAppVersion(): Promise<string>;
  claudeExtension: AugustusClaudeExtension;
  updates: AugustusUpdates;
}

interface Window {
  augustus?: AugustusAPI;
}
