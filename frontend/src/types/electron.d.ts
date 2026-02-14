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

interface AugustusAPI {
  platform: string;
  version: string;
  isElectron: boolean;
  getDataDir(): Promise<string>;
  getAppVersion(): Promise<string>;
  updates: AugustusUpdates;
}

interface Window {
  augustus?: AugustusAPI;
}
