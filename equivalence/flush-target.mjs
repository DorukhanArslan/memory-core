// Fixture transport only: the original TypeScript owner prepares every target.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TARGET = "memory/2026-09-25.md";
const failureCodes = { mkdir: "EACCES", open: "EIO", close: "EIO" };
const validationMessages = new Set([
  "Invalid memory flush target path",
  "Memory flush target path must stay inside the workspace",
]);

export async function runFlushTarget(input, importReference) {
  if (input.failOperation !== undefined && !Object.hasOwn(failureCodes, input.failOperation)) {
    throw Error("Unsupported flush target failure operation");
  }
  if (input.rejectAt !== undefined && ![1, 2, 3].includes(input.rejectAt)) {
    throw Error("Unsupported flush target authority check");
  }
  const authorityKind = input.authorityError ?? "revoked";
  if (!["revoked", "cancelled"].includes(authorityKind)) {
    throw Error("Unsupported flush target authority error");
  }
  const reference = await importReference("src/auto-reply/reply/memory-flush-session.ts");
  const temporary = await fs.promises.mkdtemp(path.join(os.tmpdir(), "memory-flush-target-"));
  const root = path.join(temporary, "workspace");
  const target = path.join(root, TARGET);
  const parent = path.dirname(target);
  const originalMkdir = fs.promises.mkdir;
  const originalOpen = fs.promises.open;
  const events = [];
  const descriptors = [];
  let checks = 0;
  let authorityError;
  let injectedError;
  const isClosed = (fd) => {
    try { fs.fstatSync(fd); }
    catch (error) {
      if (error.code === "EBADF") return true;
      throw error;
    }
    return false;
  };
  const failure = (operation) => {
    if (input.failOperation === operation) {
      injectedError = Object.assign(new Error(`Injected ${operation} failure`), {
        code: failureCodes[operation], syscall: operation,
        path: operation === "mkdir" ? parent : target,
      });
      throw injectedError;
    }
  };
  const assertCurrent = () => {
    checks += 1;
    events.push(`assert:${checks}`);
    if (checks === input.rejectAt) {
      authorityError = new Error(`Flush target ${authorityKind} at check ${checks}`);
      if (authorityKind === "cancelled") authorityError.name = "AbortError";
      throw authorityError;
    }
  };
  const normalize = (error) => {
    if (error === authorityError) return {
      kind: "authority", reason: authorityKind, check: checks, message: error.message,
    };
    if (error === injectedError) return {
      kind: "os", code: failureCodes[input.failOperation], operation: input.failOperation,
      path: input.failOperation === "mkdir" ? "memory" : TARGET,
    };
    if (validationMessages.has(error.message)) return { kind: "validation", message: error.message };
    const diagnostic = {
      kind: "unexpected", name: error.name,
      message: String(error.message).replaceAll(root, "@workspace"),
    };
    for (const key of ["code", "errno", "syscall", "path"]) {
      if (error[key] !== undefined) diagnostic[key] = typeof error[key] === "string"
        ? error[key].replaceAll(root, "@workspace") : error[key];
    }
    return diagnostic;
  };
  try {
    await originalMkdir(root);
    if (input.existingHex !== undefined) {
      await originalMkdir(parent);
      await fs.promises.writeFile(target, Buffer.from(input.existingHex, "hex"));
    }
    fs.promises.mkdir = async function observedMkdir(filename, ...args) {
      if (filename === parent) {
        events.push("mkdir:memory");
        failure("mkdir");
      }
      return originalMkdir.call(this, filename, ...args);
    };
    fs.promises.open = async function observedOpen(filename, ...args) {
      const observed = filename === target;
      if (observed) {
        events.push(`open:${TARGET}`);
        failure("open");
      }
      const handle = await originalOpen.call(this, filename, ...args);
      if (observed) {
        const entry = { handle, fd: handle.fd, closeCalls: 0 };
        descriptors.push(entry);
        const originalClose = handle.close.bind(handle);
        entry.originalClose = originalClose;
        handle.close = async function observedClose() {
          entry.closeCalls += 1;
          events.push(`close:${TARGET}`);
          await originalClose();
          failure("close");
        };
      }
      return handle;
    };
    let result;
    try {
      await reference.ensureMemoryFlushTargetFile({
        workspaceDir: root, relativePath: input.relativePath.replaceAll("@workspace", root),
        assertCurrent,
      });
      result = { ok: true };
    } catch (error) {
      result = { ok: false, error: normalize(error) };
    } finally {
      fs.promises.mkdir = originalMkdir;
      fs.promises.open = originalOpen;
    }
    const directories = [];
    const files = {};
    async function visit(directory) {
      const entries = await fs.promises.readdir(directory, { withFileTypes: true });
      entries.sort((left, right) => left.name < right.name ? -1 : left.name > right.name ? 1 : 0);
      for (const entry of entries) {
        const filename = path.join(directory, entry.name);
        const relative = path.relative(root, filename).replaceAll(path.sep, "/");
        if (entry.isDirectory()) {
          directories.push(relative);
          await visit(filename);
        } else if (entry.isFile()) {
          files[relative] = { hex: (await fs.promises.readFile(filename)).toString("hex") };
        }
      }
    }
    await visit(root);
    return {
      ...result, authorityCallbackSupported: true, checks, events,
      descriptors: descriptors.map((entry) => ({
        opened: true, closeCalls: entry.closeCalls, closed: isClosed(entry.fd),
      })), directories, files,
    };
  } finally {
    fs.promises.mkdir = originalMkdir;
    fs.promises.open = originalOpen;
    // Closure is recorded before leak cleanup, never replaced by cleanup success.
    for (const entry of descriptors) if (!isClosed(entry.fd)) await entry.originalClose();
    await fs.promises.rm(temporary, { recursive: true, force: true });
  }
}
