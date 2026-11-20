import fs from "node:fs";

/** Remove the throwaway SQLite database (and its WAL/journal files). */
export default function globalTeardown(): void {
  const db = process.env.E2E_DB_PATH;
  if (!db) return;
  for (const suffix of ["", "-wal", "-shm", "-journal"]) {
    fs.rmSync(`${db}${suffix}`, { force: true });
  }
}
