const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('augustus', {
    platform: process.platform,
    version: '0.2.0',
    isElectron: true,
    getDataDir: () => ipcRenderer.invoke('get-data-dir'),
    getAppVersion: () => ipcRenderer.invoke('get-app-version'),
});
