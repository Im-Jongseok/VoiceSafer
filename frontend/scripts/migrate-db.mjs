import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import pg from "pg";

const root = new URL("../../supabase/", import.meta.url);
const value = process.env.POSTGRES_URL_NON_POOLING;
if (!value)
  throw new Error(
    "POSTGRES_URL_NON_POOLING is required; pull Vercel environment variables first.",
  );
const connection = new URL(value);
connection.searchParams.delete("sslmode");
const db = new pg.Client({
  connectionString: connection.toString(),
  ssl: {
    ca: await readFile(new URL("prod-ca-2021.crt", root), "utf8"),
    rejectUnauthorized: true,
  },
  connectionTimeoutMillis: 15000,
});
try {
  await db.connect();
  const realtime = await db.query(
    "select to_regclass('realtime.messages') as messages",
  );
  if (!realtime.rows[0].messages)
    throw new Error(
      "Realtime is not initialized. Connect a Supabase Realtime client before migrating.",
    );
  await db.query(
    "select pg_advisory_lock(hashtext('voice-vaccine-migrations'))",
  );
  await db.query(`create schema if not exists app_private;
    create table if not exists app_private.schema_migrations(version text primary key, checksum text not null, applied_at timestamptz not null default now());
    revoke all on app_private.schema_migrations from public, anon, authenticated;`);
  for (const name of (await readdir(new URL("migrations/", root)))
    .filter((name) => name.endsWith(".sql"))
    .sort()) {
    const sql = await readFile(new URL(`migrations/${name}`, root), "utf8");
    const checksum = createHash("sha256").update(sql).digest("hex");
    const previous = await db.query(
      "select checksum from app_private.schema_migrations where version = $1",
      [name],
    );
    if (previous.rowCount) {
      if (previous.rows[0].checksum !== checksum)
        throw new Error(`Applied migration was modified: ${name}`);
      console.log(`Already applied: ${name}`);
      continue;
    }
    await db.query("begin");
    try {
      await db.query(sql);
      await db.query(
        "insert into app_private.schema_migrations(version, checksum) values($1,$2)",
        [name, checksum],
      );
      await db.query("commit");
      console.log(`Applied: ${name}`);
    } catch (error) {
      await db.query("rollback");
      throw error;
    }
  }
} catch (error) {
  console.error(
    `Database migration failed (${error.code || "configuration"}): ${error.message.replaceAll(value, "[redacted]")}`,
  );
  process.exitCode = 1;
} finally {
  await db.end();
}
