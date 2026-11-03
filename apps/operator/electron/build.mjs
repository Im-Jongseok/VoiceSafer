import { spawnSync } from "node:child_process";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { packager } from "@electron/packager";

const directory = path.dirname(fileURLToPath(import.meta.url));
const ui = path.dirname(directory);
const root = path.resolve(ui, "../../services/control-api");
const output = path.join(ui, "dist", "desktop");
const staging = await mkdtemp(path.join(tmpdir(), "rehearsal-desktop-build-"));
const manifest = JSON.parse(
  await readFile(path.join(ui, "package.json"), "utf8"),
);

function run(command, args, cwd = root) {
  const result = spawnSync(command, args, {
    cwd,
    stdio: "inherit",
    shell: false,
  });
  if (result.error) throw result.error;
  if (result.status !== 0)
    throw new Error(`${command} failed (${result.status})`);
}

try {
  run(
    process.platform === "win32" ? "npm.cmd" : "npm",
    ["run", "build"],
    ui,
  );
  run("uv", [
    "run",
    "--locked",
    "--with",
    "pyinstaller==6.22.3",
    "python",
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--name",
    "rehearsal-server",
    "--distpath",
    path.join(staging, "binary"),
    "--workpath",
    path.join(staging, "work"),
    "--specpath",
    staging,
    "--paths",
    root,
    "--collect-submodules",
    "uvicorn",
    "--collect-submodules",
    "clawops.agent",
    "--collect-all",
    "faster_whisper",
    "--collect-all",
    "ctranslate2",
    "--collect-all",
    "onnxruntime",
    "--add-data",
    `${path.join(ui, "dist")}:frontend/dist`,
    "--add-data",
    `${path.join(root, "scenarios")}:scenarios`,
    path.join(directory, "server.py"),
  ]);
  const source = path.join(staging, "application");
  await mkdir(source);
  await cp(path.join(directory, "main.cjs"), path.join(source, "main.cjs"));
  await writeFile(
    path.join(source, "package.json"),
    JSON.stringify(
      {
        name: manifest.name,
        productName: manifest.productName,
        version: manifest.version,
        description: manifest.description,
        author: manifest.author,
        main: "main.cjs",
      },
      null,
      2,
    ),
  );
  const backend = path.join(staging, "backend");
  await cp(path.join(staging, "binary", "rehearsal-server"), backend, {
    recursive: true,
  });
  await mkdir(output, { recursive: true });
  const results = await packager({
    dir: source,
    out: output,
    name: manifest.productName,
    executableName: "VoiceSafer",
    platform: process.platform,
    arch: process.arch,
    electronVersion: manifest.devDependencies.electron,
    appBundleId: "kr.codyssey.phishing-rehearsal",
    appCategoryType: "public.app-category.education",
    asar: true,
    overwrite: true,
    extraResource: [backend],
  });
  for (const result of results) {
    if (process.platform === "darwin")
      run("codesign", [
        "--force",
        "--deep",
        "--sign",
        "-",
        path.join(result, `${manifest.productName}.app`),
      ]);
    console.log(`PC app: ${result}`);
  }
} finally {
  await rm(staging, { recursive: true, force: true });
}
