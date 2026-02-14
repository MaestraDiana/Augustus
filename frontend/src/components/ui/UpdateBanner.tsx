import { Download, RefreshCw, X } from 'lucide-react';
import { useState } from 'react';
import { useUpdates } from '../../hooks/useUpdates';

export default function UpdateBanner() {
  const {
    updateAvailable,
    updateVersion,
    downloading,
    downloadProgress,
    downloaded,
    error,
    downloadUpdate,
    installUpdate,
  } = useUpdates();
  const [dismissed, setDismissed] = useState(false);

  if (dismissed || (!updateAvailable && !downloading && !downloaded)) {
    return null;
  }

  return (
    <div className="update-banner">
      <div className="update-banner-content">
        {downloaded ? (
          <>
            <RefreshCw size={14} />
            <span>Update ready (v{updateVersion})</span>
            <button className="update-banner-action" onClick={installUpdate}>
              Restart to install
            </button>
          </>
        ) : downloading ? (
          <>
            <div className="update-progress-bar">
              <div
                className="update-progress-fill"
                style={{ width: `${downloadProgress}%` }}
              />
            </div>
            <span className="update-progress-text">
              Downloading... {downloadProgress}%
            </span>
          </>
        ) : (
          <>
            <Download size={14} />
            <span>Update available (v{updateVersion})</span>
            <button className="update-banner-action" onClick={downloadUpdate}>
              Download
            </button>
          </>
        )}
        {error && <span className="update-error">{error}</span>}
      </div>
      {!downloading && (
        <button
          className="update-banner-dismiss"
          onClick={() => setDismissed(true)}
          title="Dismiss"
        >
          <X size={14} />
        </button>
      )}
    </div>
  );
}
