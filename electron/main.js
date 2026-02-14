const { app, BrowserWindow, Menu, dialog, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

const DEFAULT_PORT = 8080;
const DEV_FRONTEND_PORT = 5173;
const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

let mainWindow = null;
let pythonProcess = null;

function getPort() {
    return process.env.AUGUSTUS_PORT || DEFAULT_PORT;
}

function checkPortInUse(port) {
    return new Promise((resolve) => {
        const req = http.get(`http://localhost:${port}/api/health`, (res) => {
            resolve(true);
            req.destroy();
        });
        req.on('error', () => resolve(false));
        req.setTimeout(1000, () => {
            resolve(false);
            req.destroy();
        });
    });
}

async function startPythonBackend(port) {
    const alreadyRunning = await checkPortInUse(port);
    if (alreadyRunning) {
        console.log(`Backend already running on port ${port}`);
        return;
    }

    const pythonPath = process.env.AUGUSTUS_PYTHON || 'python';
    pythonProcess = spawn(pythonPath, ['-m', 'augustus.main', '--port', String(port)], {
        cwd: path.join(__dirname, '..', 'backend'),
        stdio: ['pipe', 'pipe', 'pipe'],
    });

    pythonProcess.stdout.on('data', (data) => {
        console.log(`[Python] ${data.toString().trim()}`);
    });

    pythonProcess.stderr.on('data', (data) => {
        console.error(`[Python] ${data.toString().trim()}`);
    });

    pythonProcess.on('exit', (code) => {
        console.log(`Python process exited with code ${code}`);
        pythonProcess = null;
    });
}

async function waitForBackend(port, maxWaitMs = 30000) {
    const start = Date.now();
    while (Date.now() - start < maxWaitMs) {
        const ready = await checkPortInUse(port);
        if (ready) return true;
        await new Promise((r) => setTimeout(r, 500));
    }
    return false;
}

function createWindow(port) {
    mainWindow = new BrowserWindow({
        width: 1440,
        height: 900,
        minWidth: 1280,
        minHeight: 720,
        title: 'Augustus',
        icon: path.join(__dirname, '..', 'icons', 'augustus-icon-256.png'),
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
        },
    });

    const url = isDev
        ? `http://localhost:${DEV_FRONTEND_PORT}`
        : `http://localhost:${port}`;

    mainWindow.loadURL(url);

    if (isDev) {
        mainWindow.webContents.openDevTools();
    }

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

function buildMenu() {
    const template = [
        {
            label: 'File',
            submenu: [{ role: 'quit' }],
        },
        {
            label: 'View',
            submenu: [
                { role: 'reload' },
                { role: 'forceReload' },
                { role: 'toggleDevTools' },
                { type: 'separator' },
                { role: 'resetZoom' },
                { role: 'zoomIn' },
                { role: 'zoomOut' },
            ],
        },
        {
            label: 'Help',
            submenu: [
                {
                    label: 'About Augustus',
                    click: () => {
                        dialog.showMessageBox(mainWindow, {
                            type: 'info',
                            title: 'About Augustus',
                            message: 'Augustus - Persistent AI Identity Research Platform',
                            detail: 'Version 0.2.0',
                        });
                    },
                },
            ],
        },
    ];

    const menu = Menu.buildFromTemplate(template);
    Menu.setApplicationMenu(menu);
}

function stopPython() {
    if (!pythonProcess) return;

    console.log('Stopping Python backend...');

    // On Windows, use tree-kill pattern to ensure child processes are terminated
    if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', pythonProcess.pid, '/f', '/t']);
    } else {
        pythonProcess.kill('SIGTERM');

        setTimeout(() => {
            if (pythonProcess) {
                console.log('Force-killing Python backend...');
                pythonProcess.kill('SIGKILL');
            }
        }, 5000);
    }
}

// IPC handlers
ipcMain.handle('get-data-dir', () => {
    return app.getPath('userData');
});

ipcMain.handle('get-app-version', () => {
    return app.getVersion();
});

app.on('ready', async () => {
    const port = getPort();
    buildMenu();

    if (!isDev) {
        await startPythonBackend(port);
        const ready = await waitForBackend(port);

        if (!ready) {
            dialog.showErrorBox(
                'Backend Error',
                'Could not start the Augustus backend. Please check the logs.'
            );
            app.quit();
            return;
        }
    }

    createWindow(port);
});

app.on('window-all-closed', () => {
    stopPython();
    app.quit();
});

app.on('before-quit', () => {
    stopPython();
});
