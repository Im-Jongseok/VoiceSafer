const {
  app,
  BrowserWindow,
  Menu,
  dialog,
  shell,
  session,
} = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const ORIGIN = "http://localhost:18780";
app.setName("VoiceSafer");
// Keep the existing private profile when changing the displayed app name.
app.setPath("userData", path.join(app.getPath("appData"), "Phishing Rehearsal"));
let window;
let backend;
let quitting = false;
let initialized = false;

async function serverReady() {
  try {
    const response = await fetch(`${ORIGIN}/api/health`, {
      signal: AbortSignal.timeout(1000),
    });
    const data = await response.json();
    if (
      !response.ok ||
      data.service !== "phishing-rehearsal" ||
      data.protocol !== 1
    )
      throw new Error("PORT_CONFLICT");
    return true;
  } catch (error) {
    if (error.message === "PORT_CONFLICT" || error instanceof SyntaxError)
      throw new Error(
        "18780 포트를 다른 서버가 사용하고 있습니다. 해당 서버를 종료한 후 다시 실행해 주세요.",
      );
    return false;
  }
}

async function startServer() {
  if (await serverReady()) return;
  const profile = app.getPath("userData");
  fs.mkdirSync(profile, { recursive: true, mode: 0o700 });
  let command;
  let args;
  if (app.isPackaged) {
    command = path.join(
      process.resourcesPath,
      "backend",
      process.platform === "win32"
        ? "rehearsal-server.exe"
        : "rehearsal-server",
    );
    args = [];
  } else {
    const root = path.resolve(__dirname, "../../../services/control-api");
    command = path.join(
      root,
      ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    );
    args = [path.join(__dirname, "server.py")];
  }
  backend = spawn(command, args, {
    cwd: profile,
    env: {
      ...process.env,
      APP_CONFIG_DIR: profile,
      APP_DATA_DIR: path.join(profile, "data"),
    },
    stdio: "ignore",
    windowsHide: true,
  });
  let failed = false;
  backend.on("error", () => {
    failed = true;
  });
  backend.on("exit", () => {
    failed = true;
    if (!quitting && window && !window.isDestroyed()) {
      dialog.showErrorBox(
        "서버 연결 종료",
        "앱 서버가 종료되었습니다. 앱을 종료한 뒤 다시 실행해 주세요.",
      );
    }
  });
  for (let attempt = 0; attempt < 120; attempt++) {
    if (failed)
      throw new Error(
        "앱 서버를 시작하지 못했습니다. 앱을 다시 실행해 주세요.",
      );
    if (await serverReady()) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(
    "앱 서버 시작 시간이 초과되었습니다. 앱을 다시 실행해 주세요.",
  );
}

function openApplication() {
  shell.openExternal("https://voice-vaccine.vercel.app/");
}

function createWindow() {
  window = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 960,
    minHeight: 640,
    title: "VoiceSafer · 운영자 관제",
    show: false,
    backgroundColor: "#ffffff",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  });
  window.once("ready-to-show", () => window.show());
  window.on("page-title-updated", (event) => event.preventDefault());
  window.webContents.on("will-navigate", (event, url) => {
    const target = new URL(url);
    if (
      target.origin !== ORIGIN ||
      !["/control", "/control/scenarios"].includes(target.pathname)
    ) {
      event.preventDefault();
      if (target.origin === ORIGIN && target.pathname === "/")
        openApplication();
    }
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url === `${ORIGIN}/`) openApplication();
    return { action: "deny" };
  });
  window.loadURL(`${ORIGIN}/control`).catch(() => {
    dialog.showErrorBox(
      "관제 화면 연결 실패",
      "관제 화면을 열지 못했습니다. 앱을 다시 실행해 주세요.",
    );
  });
  window.on("closed", () => {
    window = null;
  });
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => {
    if (window) {
      if (window.isMinimized()) window.restore();
      window.show();
      window.focus();
    }
  });
  app.whenReady().then(async () => {
    session.defaultSession.setPermissionRequestHandler(
      (_contents, _permission, callback) => callback(false),
    );
    session.defaultSession.setPermissionCheckHandler(() => false);
    session.defaultSession.webRequest.onHeadersReceived((details, callback) =>
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          "Content-Security-Policy": [
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; media-src 'self' blob:; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-src 'none'; base-uri 'none'",
          ],
        },
      }),
    );
    Menu.setApplicationMenu(
      Menu.buildFromTemplate([
        ...(process.platform === "darwin"
          ? [{ role: "appMenu", label: "VoiceSafer" }]
          : []),
        {
          label: "훈련",
          submenu: [
            { label: "신청 웹 열기", click: openApplication },
            {
              label: "설정 파일 열기",
              click: async () => {
                const error = await shell.openPath(
                  path.join(app.getPath("userData"), ".env"),
                );
                if (error)
                  dialog.showErrorBox(
                    "설정 파일 확인",
                    "설정 파일을 열지 못했습니다. 앱 설정 경로를 확인해 주세요.",
                  );
              },
            },
            { type: "separator" },
            { role: "quit" },
          ],
        },
        { role: "editMenu", label: "편집" },
        { role: "viewMenu", label: "보기" },
        { role: "windowMenu", label: "창" },
      ]),
    );
    try {
      await startServer();
      initialized = true;
      createWindow();
    } catch (error) {
      dialog.showErrorBox("VoiceSafer 실행 실패", error.message);
      app.quit();
    }
  });
  app.on("activate", () => {
    if (initialized && !window && !quitting) createWindow();
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
  app.on("before-quit", () => {
    quitting = true;
    backend?.kill();
  });
  process.once("SIGTERM", () => app.quit());
  process.once("SIGINT", () => app.quit());
}
