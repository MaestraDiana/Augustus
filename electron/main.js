const { app, BrowserWindow, Menu, dialog, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const http = require('http');

// Auto-updater — only import if available (won't be in dev without npm install)
let autoUpdater, log;
try {
    autoUpdater = require('electron-updater').autoUpdater;
    log = require('electron-log');
} catch (e) {
    // Not installed in dev — that's fine
}

const DEFAULT_PORT = 8080;
const DEV_FRONTEND_PORT = 5173;
const UPDATE_CHECK_INTERVAL = 6 * 60 * 60 * 1000; // 6 hours
const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

let mainWindow = null;
let pythonProcess = null;
let updateCheckTimer = null;
let pythonStderr = [];

function getPort() {
    return process.env.AUGUSTUS_PORT || DEFAULT_PORT;
}

function checkPortInUse(port) {
    return new Promise((resolve) => {
        const req = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
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

    if (app.isPackaged) {
        // Production: look for PyInstaller frozen binary first
        const binaryName = 'augustus' + (process.platform === 'win32' ? '.exe' : '');
        const frozenPath = path.join(process.resourcesPath, 'backend', binaryName);

        if (fs.existsSync(frozenPath)) {
            console.log(`Starting frozen backend binary: ${frozenPath}`);
            pythonProcess = spawn(frozenPath, ['--port', String(port)], {
                stdio: ['pipe', 'pipe', 'pipe'],
            });
        } else {
            // Fallback: use Python interpreter even in production
            console.log(`Frozen binary not found at ${frozenPath}, falling back to Python`);
            const pythonPath = process.env.AUGUSTUS_PYTHON || 'python';
            pythonProcess = spawn(pythonPath, ['-m', 'augustus.main', '--port', String(port)], {
                cwd: path.join(__dirname, '..', 'backend'),
                stdio: ['pipe', 'pipe', 'pipe'],
            });
        }
    } else {
        // Development: always use Python interpreter
        console.log('Starting Python backend in dev mode');
        const pythonPath = process.env.AUGUSTUS_PYTHON || 'python';
        pythonProcess = spawn(pythonPath, ['-m', 'augustus.main', '--port', String(port)], {
            cwd: path.join(__dirname, '..', 'backend'),
            stdio: ['pipe', 'pipe', 'pipe'],
        });
    }

    pythonStderr = [];

    pythonProcess.stdout.on('data', (data) => {
        console.log(`[Python] ${data.toString().trim()}`);
    });

    pythonProcess.stderr.on('data', (data) => {
        const text = data.toString().trim();
        console.error(`[Python] ${text}`);
        pythonStderr.push(...text.split('\n'));
        // Keep last 50 lines to avoid unbounded growth
        if (pythonStderr.length > 50) pythonStderr.splice(0, pythonStderr.length - 50);
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
        : `http://127.0.0.1:${port}`;

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
                            detail: `Version ${app.getVersion()}`,
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

// --- Auto-updater setup ---

function setupAutoUpdater() {
    if (!app.isPackaged || !autoUpdater) {
        console.log('Auto-updater disabled (dev mode or electron-updater not available)');
        return;
    }

    // Configure
    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = true;

    if (log) {
        autoUpdater.logger = log;
        autoUpdater.logger.transports.file.level = 'info';
    }

    // Forward events to renderer
    autoUpdater.on('update-available', (info) => {
        mainWindow?.webContents.send('update-available', { version: info.version });
    });

    autoUpdater.on('update-not-available', () => {
        mainWindow?.webContents.send('update-not-available');
    });

    autoUpdater.on('download-progress', (progress) => {
        mainWindow?.webContents.send('download-progress', progress);
    });

    autoUpdater.on('update-downloaded', () => {
        mainWindow?.webContents.send('update-downloaded');
    });

    autoUpdater.on('error', (err) => {
        mainWindow?.webContents.send('update-error', err?.message || String(err));
    });

    // Initial check
    autoUpdater.checkForUpdates().catch((err) => {
        console.error('Auto-update check failed:', err);
    });

    // Periodic checks
    updateCheckTimer = setInterval(() => {
        autoUpdater.checkForUpdates().catch((err) => {
            console.error('Auto-update check failed:', err);
        });
    }, UPDATE_CHECK_INTERVAL);
}

// --- First-launch flag ---

function writeFirstLaunchFlag() {
    const metaPath = path.join(app.getPath('userData'), 'install-meta.json');
    if (!fs.existsSync(metaPath)) {
        const meta = {
            firstLaunch: new Date().toISOString(),
            version: app.getVersion(),
        };
        try {
            fs.writeFileSync(metaPath, JSON.stringify(meta, null, 2), 'utf-8');
            console.log('First-launch flag written:', metaPath);
        } catch (err) {
            console.error('Failed to write first-launch flag:', err);
        }
    }
}

// --- Claude Desktop Extension management ---

const CLAUDE_EXT_ID = 'local.mcpb.machine-pareidolia.augustus';

function getClaudeDir() {
    return path.join(app.getPath('appData'), 'Claude');
}

function isClaudeDesktopInstalled() {
    return fs.existsSync(getClaudeDir());
}

function getBackendBinaryPath() {
    const binaryName = 'augustus' + (process.platform === 'win32' ? '.exe' : '');
    if (app.isPackaged) {
        return path.join(process.resourcesPath, 'backend', binaryName);
    }
    // Dev mode: use the PyInstaller output if available, else fall back to python
    const devBinary = path.join(__dirname, '..', 'backend', 'dist', 'augustus', binaryName);
    if (fs.existsSync(devBinary)) return devBinary;
    return null;
}

function buildExtensionManifest(binaryPath) {
    return {
        manifest_version: '0.3',
        name: 'augustus',
        display_name: 'Augustus',
        version: app.getVersion(),
        description: 'Persistent AI identity research platform. Observe agent sessions, manage attractor basins, review tier proposals and evaluator flags, search semantic memory, and annotate agent behavior.',
        author: { name: 'Machine Pareidolia', url: 'https://getaugustus.com' },
        homepage: 'https://getaugustus.com',
        icon: 'icon.png',
        license: 'MIT',
        server: {
            type: 'binary',
            entry_point: binaryPath,
            mcp_config: {
                command: binaryPath,
                args: ['--mcp'],
                env: { AUGUSTUS_DATA_DIR: '${user_config.data_dir}' },
            },
        },
        user_config: {
            data_dir: {
                type: 'directory',
                title: 'Augustus Data Directory',
                description: 'Directory containing your Augustus databases. Auto-configured by the Augustus app.',
                required: true,
            },
        },
        tools: [
            { name: 'get_session_summary', description: 'Get a structured summary of a specific session.' },
            { name: 'get_session_transcript', description: 'Retrieve the complete transcript for a session.' },
            { name: 'get_close_report', description: 'Retrieve the close report for a session.' },
            { name: 'get_basin_trajectory', description: 'Get alpha trajectory for a specific basin over recent sessions.' },
            { name: 'get_all_trajectories', description: 'Get all basin trajectories for an agent.' },
            { name: 'search_sessions', description: 'Semantic search across session content for an agent.' },
            { name: 'get_evaluator_flags', description: 'Get flagged sessions for an agent.' },
            { name: 'get_tier_proposals', description: 'Get tier modification proposals for an agent.' },
            { name: 'list_agents', description: 'List all registered agents with summary statistics.' },
            { name: 'list_sessions', description: 'List recent sessions for an agent with pending review counts.' },
            { name: 'search_all', description: 'Cross-agent semantic search.' },
            { name: 'add_observation', description: 'Add a human evaluation note or observation.' },
            { name: 'search_observations', description: 'Search observations and annotations for an agent.' },
            { name: 'get_agent_annotations', description: 'Get annotations for an agent.' },
            { name: 'delete_annotation', description: 'Delete a specific annotation by its ID.' },
            { name: 'approve_tier_proposal', description: 'Approve a pending tier modification proposal.' },
            { name: 'flag_session', description: 'Flag a session for attention.' },
            { name: 'reject_tier_proposal', description: 'Reject a pending tier proposal with rationale.' },
            { name: 'modify_tier_proposal', description: 'Approve a proposal with modified parameters.' },
            { name: 'get_pending_review_items', description: 'Get all items awaiting brain review for an agent.' },
            { name: 'resolve_flag', description: 'Resolve an evaluator flag.' },
            { name: 'create_basin', description: 'Brain-initiated basin creation (bypasses proposal flow).' },
            { name: 'modify_basin', description: 'Direct basin parameter adjustment (bypasses proposal flow).' },
            { name: 'deprecate_basin', description: 'Soft-deprecate a basin.' },
            { name: 'undeprecate_basin', description: 'Restore a deprecated basin to active tracking.' },
            { name: 'lock_basin', description: 'Lock a basin so body cannot modify it.' },
            { name: 'unlock_basin', description: 'Remove brain lock from a basin.' },
            { name: 'set_basin_bounds', description: 'Set alpha bounds that body must respect.' },
            { name: 'get_basin_history', description: 'Get recent modifications for a specific basin (audit trail).' },
            { name: 'create_proposal', description: 'Create a proposal that sits in the pending queue for later review.' },
        ],
        compatibility: { platforms: ['win32', 'darwin', 'linux'] },
    };
}

function checkClaudeExtensionStatus() {
    if (!isClaudeDesktopInstalled()) {
        return { installed: false, enabled: false, claudeDesktopFound: false, needsReinstall: false };
    }

    const claudeDir = getClaudeDir();
    const registryPath = path.join(claudeDir, 'extensions-installations.json');
    const settingsPath = path.join(claudeDir, 'Claude Extensions Settings', `${CLAUDE_EXT_ID}.json`);
    const manifestPath = path.join(claudeDir, 'Claude Extensions', CLAUDE_EXT_ID, 'manifest.json');

    let registryEntry = false;
    let manifestExists = false;
    let versionMatch = false;
    let enabled = false;

    // Check registry
    if (fs.existsSync(registryPath)) {
        try {
            const registry = JSON.parse(fs.readFileSync(registryPath, 'utf-8'));
            registryEntry = !!(registry.extensions && registry.extensions[CLAUDE_EXT_ID]);
        } catch { /* corrupt file */ }
    }

    // Check manifest actually exists on disk
    if (fs.existsSync(manifestPath)) {
        manifestExists = true;
        try {
            const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
            versionMatch = manifest.version === app.getVersion();
        } catch { /* corrupt file */ }
    }

    // Only consider "installed" if both registry AND manifest exist on disk
    const installed = registryEntry && manifestExists;
    // Flag reinstall needed if registry exists but manifest is missing or version mismatches
    const needsReinstall = registryEntry && (!manifestExists || !versionMatch);

    if (installed && fs.existsSync(settingsPath)) {
        try {
            const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
            enabled = settings.isEnabled === true;
        } catch { /* corrupt file */ }
    }

    return { installed, enabled, claudeDesktopFound: true, needsReinstall };
}

function installClaudeExtension(dataDir) {
    const binaryPath = getBackendBinaryPath();
    if (!binaryPath) {
        return { success: false, error: 'Backend binary not found. Build the backend first.' };
    }
    if (!fs.existsSync(binaryPath)) {
        return { success: false, error: `Backend binary not found at ${binaryPath}` };
    }
    if (!isClaudeDesktopInstalled()) {
        return { success: false, error: 'Claude Desktop not found. Install Claude Desktop first.' };
    }

    const claudeDir = getClaudeDir();
    const extDir = path.join(claudeDir, 'Claude Extensions', CLAUDE_EXT_ID);
    const settingsDir = path.join(claudeDir, 'Claude Extensions Settings');
    const registryPath = path.join(claudeDir, 'extensions-installations.json');

    try {
        // 1. Create extension directory and write manifest
        fs.mkdirSync(extDir, { recursive: true });
        const manifest = buildExtensionManifest(binaryPath);
        const manifestJson = JSON.stringify(manifest, null, 2);
        fs.writeFileSync(path.join(extDir, 'manifest.json'), manifestJson, 'utf-8');

        // 2. Copy icon
        const iconSrc = app.isPackaged
            ? path.join(process.resourcesPath, 'app.asar.unpacked', 'icons', 'augustus-icon-512.png')
            : path.join(__dirname, '..', 'icons', 'augustus-icon-512.png');
        // Try multiple icon locations
        const iconCandidates = [
            iconSrc,
            path.join(__dirname, '..', 'icons', 'augustus-icon-512.png'),
            path.join(process.resourcesPath || '', 'icons', 'augustus-icon-512.png'),
        ];
        for (const candidate of iconCandidates) {
            if (fs.existsSync(candidate)) {
                fs.copyFileSync(candidate, path.join(extDir, 'icon.png'));
                break;
            }
        }

        // 3. Update registry
        let registry = { extensions: {} };
        if (fs.existsSync(registryPath)) {
            try {
                registry = JSON.parse(fs.readFileSync(registryPath, 'utf-8'));
                if (!registry.extensions) registry.extensions = {};
            } catch { /* start fresh */ }
        }

        const hash = crypto.createHash('sha256').update(manifestJson).digest('hex');
        registry.extensions[CLAUDE_EXT_ID] = {
            id: CLAUDE_EXT_ID,
            version: app.getVersion(),
            hash,
            installedAt: new Date().toISOString(),
            manifest,
            signatureInfo: { status: 'unsigned' },
            source: 'local',
        };
        fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2), 'utf-8');

        // 4. Create settings with data_dir pre-populated
        fs.mkdirSync(settingsDir, { recursive: true });
        const extSettings = {
            isEnabled: true,
            userConfig: { data_dir: dataDir },
        };
        fs.writeFileSync(
            path.join(settingsDir, `${CLAUDE_EXT_ID}.json`),
            JSON.stringify(extSettings, null, 2),
            'utf-8'
        );

        console.log(`Claude Desktop extension installed: ${extDir}`);
        return { success: true };
    } catch (err) {
        console.error('Failed to install Claude extension:', err);
        return { success: false, error: err.message };
    }
}

function uninstallClaudeExtension() {
    if (!isClaudeDesktopInstalled()) {
        return { success: false, error: 'Claude Desktop not found.' };
    }

    const claudeDir = getClaudeDir();
    const extDir = path.join(claudeDir, 'Claude Extensions', CLAUDE_EXT_ID);
    const settingsPath = path.join(claudeDir, 'Claude Extensions Settings', `${CLAUDE_EXT_ID}.json`);
    const registryPath = path.join(claudeDir, 'extensions-installations.json');

    try {
        // Remove from registry first (always works even if files are locked)
        if (fs.existsSync(registryPath)) {
            try {
                const registry = JSON.parse(fs.readFileSync(registryPath, 'utf-8'));
                if (registry.extensions && registry.extensions[CLAUDE_EXT_ID]) {
                    delete registry.extensions[CLAUDE_EXT_ID];
                    fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2), 'utf-8');
                }
            } catch { /* ignore */ }
        }

        // Remove settings file
        if (fs.existsSync(settingsPath)) {
            try { fs.unlinkSync(settingsPath); } catch { /* may be locked */ }
        }

        // Remove extension directory (may fail if Claude Desktop has files locked)
        if (fs.existsSync(extDir)) {
            try {
                fs.rmSync(extDir, { recursive: true, force: true });
            } catch (rmErr) {
                console.warn('Could not fully remove extension dir (files may be locked by Claude Desktop):', rmErr.message);
                // Still counts as success — registry entry is gone, so Claude won't load it
            }
        }

        console.log('Claude Desktop extension uninstalled');
        return { success: true };
    } catch (err) {
        console.error('Failed to uninstall Claude extension:', err);
        return { success: false, error: err.message };
    }
}

// --- IPC handlers ---

ipcMain.handle('get-data-dir', () => {
    return app.getPath('userData');
});

ipcMain.handle('get-app-version', () => {
    return app.getVersion();
});

ipcMain.handle('check-for-update', () => {
    if (autoUpdater && app.isPackaged) {
        return autoUpdater.checkForUpdates();
    }
    return null;
});

ipcMain.handle('download-update', () => {
    if (autoUpdater && app.isPackaged) {
        return autoUpdater.downloadUpdate();
    }
    return null;
});

ipcMain.handle('install-update', () => {
    if (autoUpdater && app.isPackaged) {
        autoUpdater.quitAndInstall();
    }
});

ipcMain.handle('check-claude-extension', () => {
    return checkClaudeExtensionStatus();
});

ipcMain.handle('install-claude-extension', (_, dataDir) => {
    return installClaudeExtension(dataDir);
});

ipcMain.handle('uninstall-claude-extension', () => {
    return uninstallClaudeExtension();
});

// --- App lifecycle ---

app.on('ready', async () => {
    const port = getPort();
    buildMenu();
    writeFirstLaunchFlag();

    if (!isDev) {
        await startPythonBackend(port);
        const ready = await waitForBackend(port);

        if (!ready) {
            const logDir = app.getPath('logs');
            const stderrTail = pythonStderr.slice(-10).join('\n').trim();
            const detail = stderrTail
                ? `Last error output:\n${stderrTail}\n\nLog directory:\n${logDir}`
                : `Log directory:\n${logDir}`;
            dialog.showMessageBoxSync({
                type: 'error',
                title: 'Backend Error',
                message: 'Could not start the Augustus backend.',
                detail,
                buttons: ['OK'],
            });
            app.quit();
            return;
        }
    }

    createWindow(port);
    setupAutoUpdater();
});

app.on('window-all-closed', () => {
    if (updateCheckTimer) {
        clearInterval(updateCheckTimer);
        updateCheckTimer = null;
    }
    stopPython();
    app.quit();
});

app.on('before-quit', () => {
    if (updateCheckTimer) {
        clearInterval(updateCheckTimer);
        updateCheckTimer = null;
    }
    stopPython();
});
