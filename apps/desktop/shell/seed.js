"use strict";
// First run in managed mode: unpack the code that came with the App into
// <root>. The dependency layers are large, so they are unpacked here with
// progress; the steps that need Python and Git run from the base just unpacked
// (bootstrap/install_seed.py), the same script the command-line installers use.
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const zlib = require("node:zlib");
const store = require("./store");

const BLOCK = 512;
const WORK = ".seed-work";
const EXTRACTION_SHARE = 92;
// Antivirus scanners and backup tools hold new files briefly on Windows.
const LOCKED_FILE_CODES = new Set(["EPERM", "EBUSY", "EACCES"]);
const LOCKED_FILE_ATTEMPTS = 8;
const LOCKED_FILE_DELAY_MS = 250;
// Used when a seed does not say how large it unpacks to.
const UNPACKED_PER_ARCHIVE_BYTE = 4;
const DISK_MARGIN_BYTES = 512 * 1024 * 1024;

class SeedError extends Error {}

function readSeedManifest(seedDirectory) {
  try {
    return JSON.parse(fs.readFileSync(path.join(seedDirectory, "seed.json"), "utf8"));
  } catch (error) {
    throw new SeedError(`this App has no usable built-in copy: ${error.message}`);
  }
}

function field(header, start, length) {
  const end = header.indexOf(0, start);
  return header.toString("utf8", start, end >= start && end < start + length ? end : start + length);
}

function octal(header, start, length) {
  if (header[start] & 0x80) {
    let value = 0;
    for (let index = start + 1; index < start + length; index += 1) value = value * 256 + header[index];
    return value;
  }
  const text = field(header, start, length).trim();
  return text ? Number.parseInt(text, 8) : 0;
}

function parsePax(buffer) {
  const values = {};
  let offset = 0;
  while (offset < buffer.length) {
    const space = buffer.indexOf(0x20, offset);
    if (space < 0) break;
    const length = Number.parseInt(buffer.toString("utf8", offset, space), 10);
    if (!Number.isInteger(length) || length <= 0) break;
    const record = buffer.toString("utf8", space + 1, offset + length - 1);
    const separator = record.indexOf("=");
    if (separator > 0) values[record.slice(0, separator)] = record.slice(separator + 1);
    offset += length;
  }
  return values;
}

/** Join an archive member under `destination`, refusing anything that leaves it. */
function memberPath(destination, name) {
  const cleaned = name.replace(/\/+$/, "");
  if (!cleaned || path.posix.isAbsolute(cleaned) || /^[A-Za-z]:/.test(cleaned) ||
      cleaned.includes("\\") || cleaned.split("/").some((part) => part === ".." || part === "")) {
    throw new SeedError(`invalid path in the built-in copy: ${name}`);
  }
  return path.join(destination, ...cleaned.split("/"));
}

function linkAllowed(destination, member, target, builtRoot) {
  if (path.isAbsolute(target)) return Boolean(builtRoot) && target.startsWith(`${builtRoot}/`);
  const resolved = path.resolve(path.dirname(member), target);
  return resolved === destination || resolved.startsWith(destination + path.sep);
}

/** One tar member at a time from a stream of decompressed chunks. */
class TarWriter {
  constructor(destination, builtRoot) {
    this.destination = destination;
    this.builtRoot = builtRoot;
    this.pending = [];
    this.pendingBytes = 0;
    this.descriptor = null;
    this.remaining = 0;
    this.padding = 0;
    this.collecting = null;
    this.member = null;
    this.pax = {};
    this.longName = null;
    this.longLink = null;
    this.ended = false;
  }

  take(count) {
    const merged = this.pending.length === 1 ? this.pending[0] : Buffer.concat(this.pending);
    const taken = merged.subarray(0, count);
    const rest = merged.subarray(count);
    this.pending = rest.length ? [rest] : [];
    this.pendingBytes = rest.length;
    return taken;
  }

  write(chunk) {
    this.pending.push(chunk);
    this.pendingBytes += chunk.length;
    while (!this.ended) {
      if (this.padding) {
        const skip = Math.min(this.padding, this.pendingBytes);
        if (!skip) return;
        this.take(skip);
        this.padding -= skip;
        if (this.padding) return;
      }
      if (this.remaining) {
        const count = Math.min(this.remaining, this.pendingBytes);
        if (!count) return;
        const data = this.take(count);
        if (this.collecting) this.collecting.chunks.push(data);
        else fs.writeSync(this.descriptor, data);
        this.remaining -= count;
        if (this.remaining) return;
        this.finishMember();
        continue;
      }
      if (this.pendingBytes < BLOCK) return;
      this.header(this.take(BLOCK));
    }
  }

  finishMember() {
    this.padding = this.memberPadding;
    if (this.collecting) {
      const { kind, chunks } = this.collecting;
      const data = Buffer.concat(chunks);
      this.collecting = null;
      if (kind === "x") this.pax = parsePax(data);
      else if (kind === "L") this.longName = data.toString("utf8").replace(/\0+$/, "");
      else if (kind === "K") this.longLink = data.toString("utf8").replace(/\0+$/, "");
      return;
    }
    const descriptor = this.descriptor;
    this.descriptor = null;
    const { mode, mtime } = this.member;
    fs.fchmodSync(descriptor, mode & 0o777);
    fs.futimesSync(descriptor, mtime, mtime);
    fs.closeSync(descriptor);
    this.member = null;
  }

  header(block) {
    if (block.every((byte) => byte === 0)) {
      this.ended = true;
      return;
    }
    const prefix = field(block, 345, 155);
    const shortName = field(block, 0, 100);
    const baseName = prefix && field(block, 257, 5) === "ustar" ? `${prefix}/${shortName}` : shortName;
    const size = Number(this.pax.size || octal(block, 124, 12));
    const type = String.fromCharCode(block[156] || 48);
    const padding = (BLOCK - (size % BLOCK)) % BLOCK;
    this.memberPadding = padding;
    if ("xgLK".includes(type)) {
      this.collecting = { kind: type, chunks: [] };
      this.remaining = size;
      if (!size) this.finishMember();
      return;
    }
    const name = this.pax.path || this.longName || baseName;
    const linkName = this.pax.linkpath || this.longLink || field(block, 157, 100);
    const mode = octal(block, 100, 8) || 0o644;
    const mtime = Number(this.pax.mtime || octal(block, 136, 12));
    this.pax = {};
    this.longName = null;
    this.longLink = null;
    const target = memberPath(this.destination, name);
    if (type === "5") {
      fs.mkdirSync(target, { recursive: true });
      return;
    }
    fs.mkdirSync(path.dirname(target), { recursive: true });
    if (type === "2") {
      if (!linkAllowed(this.destination, target, linkName, this.builtRoot)) {
        throw new SeedError(`a link in the built-in copy leaves it: ${name}`);
      }
      fs.rmSync(target, { force: true });
      fs.symlinkSync(linkName, target);
      return;
    }
    if (type === "1") {
      fs.rmSync(target, { force: true });
      fs.linkSync(memberPath(this.destination, linkName), target);
      return;
    }
    if (type !== "0" && type !== "7") throw new SeedError(`unsupported entry in the built-in copy: ${name}`);
    fs.rmSync(target, { force: true });
    this.descriptor = fs.openSync(target, "w", 0o600);
    this.member = { mode, mtime };
    this.remaining = size;
    if (!size) this.finishMember();
  }

  close() {
    if (this.descriptor !== null) {
      fs.closeSync(this.descriptor);
      this.descriptor = null;
    }
  }
}

/** Unpack one `.tar.zst`, reporting compressed bytes as they are read. */
async function extractArchive(archive, destination, { builtRoot, onBytes = () => {} } = {}) {
  if (typeof zlib.createZstdDecompress !== "function") {
    throw new SeedError("this build of the App cannot read its built-in copy");
  }
  fs.mkdirSync(destination, { recursive: true });
  const source = fs.createReadStream(archive, { highWaterMark: 1 << 20 });
  source.on("data", (chunk) => onBytes(chunk.length));
  const decompressed = source.pipe(zlib.createZstdDecompress());
  source.on("error", (error) => decompressed.destroy(error));
  const writer = new TarWriter(destination, builtRoot);
  try {
    for await (const chunk of decompressed) writer.write(chunk);
  } finally {
    writer.close();
  }
}

/** Run a file operation, waiting out another program that holds the file. */
async function whenUnlocked(operation, { attempts = LOCKED_FILE_ATTEMPTS, delayMs = LOCKED_FILE_DELAY_MS } = {}) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      return operation();
    } catch (error) {
      if (!LOCKED_FILE_CODES.has(error.code) || attempt >= attempts) throw error;
      await new Promise((resolve) => { setTimeout(resolve, delayMs * attempt); });
    }
  }
}

async function moveEach(source, target, retry) {
  if (!fs.existsSync(source)) return;
  fs.mkdirSync(target, { recursive: true });
  for (const name of fs.readdirSync(source)) {
    const destination = path.join(target, name);
    await whenUnlocked(() => {
      if (fs.existsSync(destination)) fs.rmSync(path.join(source, name), { recursive: true, force: true });
      else fs.renameSync(path.join(source, name), destination);
    }, retry);
  }
}

function formatGigabytes(bytes) {
  const gigabytes = bytes / 1024 ** 3;
  return `${gigabytes < 10 ? gigabytes.toFixed(1) : Math.round(gigabytes)} GB`;
}

/** How much the disk holding `directory` has free, or null when it can't be told. */
function freeBytes(directory, statfs = fs.statfsSync) {
  let current = path.resolve(directory);
  while (!fs.existsSync(current) && path.dirname(current) !== current) current = path.dirname(current);
  try {
    const { bavail, bsize } = statfs(current);
    return Number(bavail) * Number(bsize);
  } catch {
    return null;
  }
}

/** Stop before unpacking, with the numbers, when the disk can't hold the result. */
function assertDiskSpace(root, manifest, archives, { statfs, partial = false } = {}) {
  if (!archives.length) return;
  const packed = archives.reduce((sum, archive) => sum + fs.statSync(archive).size, 0);
  const unpacked = !partial && Number.isSafeInteger(manifest.unpacked_bytes) && manifest.unpacked_bytes > 0
    ? manifest.unpacked_bytes
    : packed * UNPACKED_PER_ARCHIVE_BYTE;
  const needed = unpacked + DISK_MARGIN_BYTES;
  const free = freeBytes(root, statfs);
  if (free !== null && free < needed) {
    throw new SeedError(
      `OpenProgram needs about ${formatGigabytes(needed)} of free disk space to finish setting up, ` +
      `and this disk has ${formatGigabytes(free)} free. Free up some space, then try again.`,
    );
  }
}

function assertSeedable(root) {
  if (fs.existsSync(path.join(root, ".seeding"))) return;
  let entries;
  try {
    entries = fs.readdirSync(root);
  } catch (error) {
    if (error.code === "ENOENT") return;
    throw error;
  }
  const unrelated = entries.filter((name) => name !== "cli" && name !== WORK);
  if (unrelated.length) {
    throw new SeedError(`${root} already holds files that are not a version store`);
  }
}

function runInstaller({ python, seedDirectory, root, restoring, spawnProcess = spawn }) {
  const script = path.join(seedDirectory, "bootstrap", "install_seed.py");
  const options = restoring ? ["--point-at-seed"] : [];
  return new Promise((resolve, reject) => {
    let output = "";
    const child = spawnProcess(python, ["-I", "-B", script, "--seed", seedDirectory, "--root", root, ...options], {
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    child.stdout.on("data", (data) => { output += data; });
    child.stderr.on("data", (data) => { output += data; });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new SeedError(output.trim().slice(-1000) || `setup stopped with code ${code}`));
    });
  });
}

function basePython(root, base, platform = process.platform) {
  return platform === "win32"
    ? path.join(root, "bases", base, "python", "python.exe")
    : path.join(root, "bases", base, "python", "bin", "python3");
}

/**
 * Unpack the built-in copy into `root`. Interrupted runs start over: `.seeding`
 * is written first and removed last, by the installer. A non-empty `repo/` is
 * never overwritten.
 */
async function seed({
  root, seedDirectory, onProgress = () => {}, platform = process.platform, spawnProcess, restoring = false,
  statfs, retry,
}) {
  const manifest = readSeedManifest(seedDirectory);
  assertSeedable(root);
  const archives = ["base.tar.zst", "version.tar.zst"].map((name) => path.join(seedDirectory, name));
  const work = path.join(root, WORK);
  await whenUnlocked(() => fs.rmSync(work, { recursive: true, force: true }), retry);
  const haveBase = fs.existsSync(path.join(root, "bases", manifest.base));
  const haveVersion = fs.existsSync(path.join(root, "versions", manifest.version));
  const pending = archives.filter((_archive, index) => !(index === 0 ? haveBase : haveVersion));
  assertDiskSpace(root, manifest, pending, { statfs, partial: pending.length !== archives.length });
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(path.join(root, ".seeding"), `${process.pid}\n`);

  const total = archives.reduce((sum, archive) => sum + fs.statSync(archive).size, 0) || 1;
  let done = 0;
  let reported = -1;
  const report = () => {
    const percent = Math.min(EXTRACTION_SHARE, Math.floor((done / total) * EXTRACTION_SHARE));
    if (percent !== reported) onProgress((reported = percent));
  };
  report();

  for (const [archive, present] of [[archives[0], haveBase], [archives[1], haveVersion]]) {
    if (present) {
      done += fs.statSync(archive).size;
      report();
      continue;
    }
    await extractArchive(archive, work, {
      builtRoot: manifest.built_root,
      onBytes(bytes) {
        done += bytes;
        report();
      },
    });
  }
  await moveEach(path.join(work, "bases"), path.join(root, "bases"), retry);
  await moveEach(path.join(work, "pristine-frontend"), path.join(root, "pristine-frontend"), retry);
  await moveEach(path.join(work, "versions"), path.join(root, "versions"), retry);
  await whenUnlocked(() => fs.rmSync(work, { recursive: true, force: true }), retry);

  await runInstaller({
    python: basePython(root, manifest.base, platform), seedDirectory, root, restoring, spawnProcess,
  });
  onProgress(100);
  return manifest;
}

/**
 * The recovery page's "Restore the built-in copy": only ever fills an empty
 * `repo/`, and leaves every version already on disk alone.
 */
async function restoreBuiltIn({ root, seedDirectory, onProgress, platform, spawnProcess }) {
  if (!store.repoIsEmpty(root)) {
    return { restored: false, message: "The code folder isn't empty, so nothing was changed." };
  }
  if (!fs.existsSync(path.join(seedDirectory, "seed.json"))) {
    return { restored: false, message: "This App has no built-in copy to restore." };
  }
  fs.writeFileSync(path.join(root, ".seeding"), `${process.pid}\n`);
  await seed({ root, seedDirectory, onProgress, platform, spawnProcess, restoring: true });
  return { restored: true, message: "The built-in copy is back. Restarting." };
}

module.exports = {
  SeedError, assertDiskSpace, basePython, extractArchive, freeBytes, readSeedManifest, restoreBuiltIn, seed, whenUnlocked,
};
