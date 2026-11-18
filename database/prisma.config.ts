// Prisma configuration (Prisma 7: connection settings live here, not in schema.prisma).
//
// Connection URL, first match wins:
//   MIGRATE_DATABASE_URL   preferred for migrations. On Neon use the *direct* host (without
//                          "-pooler"): migrations take advisory locks that a PgBouncer pool
//                          does not support.
//   DATABASE_URL           standard Prisma variable
//   AGRISENSE_DATABASE_URL the backend's variable (read from backend/.env when present)
import { config as loadEnv } from "dotenv";
import { defineConfig } from "prisma/config";

loadEnv({ path: "../backend/.env", quiet: true });
loadEnv({ path: ".env", override: true, quiet: true });

let url =
  process.env.MIGRATE_DATABASE_URL ?? process.env.DATABASE_URL ?? process.env.AGRISENSE_DATABASE_URL;

if (url && !/^postgres(ql)?:\/\//.test(url)) {
  throw new Error(
    "Prisma migrations target PostgreSQL only. Set MIGRATE_DATABASE_URL or DATABASE_URL to a " +
      "postgresql:// URL (SQLite development databases are created by the backend itself).",
  );
}

if (url) {
  // `sslnegotiation=direct` is a libpq (Python backend) option; Prisma's driver does not take it.
  const parsed = new URL(url);
  parsed.searchParams.delete("sslnegotiation");
  url = parsed.toString();
}

export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: { path: "prisma/migrations" },
  datasource: {
    url,
    // Only needed by `prisma migrate dev` (creating new migrations) on hosts where the user may
    // not create databases, e.g. Neon: point it at a second, empty Neon branch or database.
    shadowDatabaseUrl: process.env.SHADOW_DATABASE_URL,
  },
});
