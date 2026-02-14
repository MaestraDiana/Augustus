import { useState, useEffect, useCallback } from 'react';

interface UpdateState {
  updateAvailable: boolean;
  updateVersion: string | null;
  downloading: boolean;
  downloadProgress: number;
  downloaded: boolean;
  error: string | null;
  checkForUpdate: () => void;
  downloadUpdate: () => void;
  installUpdate: () => void;
}

export function useUpdates(): UpdateState {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [updateVersion, setUpdateVersion] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [downloaded, setDownloaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updates = window.augustus?.updates;

  useEffect(() => {
    if (!updates) return;

    updates.onUpdateAvailable((info) => {
      setUpdateAvailable(true);
      setUpdateVersion(info.version);
      setError(null);
    });

    updates.onUpdateNotAvailable(() => {
      setUpdateAvailable(false);
    });

    updates.onDownloadProgress((progress) => {
      setDownloading(true);
      setDownloadProgress(Math.round(progress.percent));
    });

    updates.onUpdateDownloaded(() => {
      setDownloading(false);
      setDownloaded(true);
      setDownloadProgress(100);
    });

    updates.onUpdateError((err) => {
      setDownloading(false);
      setError(err);
    });

    return () => {
      updates.removeAllListeners();
    };
  }, [updates]);

  const checkForUpdate = useCallback(() => {
    updates?.checkForUpdate().catch(() => {});
  }, [updates]);

  const downloadUpdate = useCallback(() => {
    if (!updates) return;
    setDownloading(true);
    setError(null);
    updates.downloadUpdate().catch((err) => {
      setDownloading(false);
      setError(String(err));
    });
  }, [updates]);

  const installUpdate = useCallback(() => {
    updates?.installUpdate().catch(() => {});
  }, [updates]);

  return {
    updateAvailable,
    updateVersion,
    downloading,
    downloadProgress,
    downloaded,
    error,
    checkForUpdate,
    downloadUpdate,
    installUpdate,
  };
}
