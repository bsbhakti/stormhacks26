import { Pool } from "pg";

function databaseUrl() {
  const value = process.env.TIMESCALE_SERVICE_URL;
  if (!value) {
    throw new Error(
      "TIMESCALE_SERVICE_URL is not set; copy web/.env.example to web/.env.local",
    );
  }
  return value;
}

function poolConfig() {
  const url = new URL(databaseUrl());
  return {
    host: url.hostname,
    port: Number(url.port || 5432),
    user: decodeURIComponent(url.username),
    password: decodeURIComponent(url.password),
    database: url.pathname.replace(/^\//, ""),
    // Tiger Cloud uses a cert chain Node does not trust by default.
    ssl: { rejectUnauthorized: false },
    max: 6,
    idleTimeoutMillis: 20_000,
    connectionTimeoutMillis: 8_000,
  };
}

const globalForDb = globalThis as typeof globalThis & {
  triagePoolV2?: Pool;
};

export function getPool() {
  if (!globalForDb.triagePoolV2) {
    globalForDb.triagePoolV2 = new Pool(poolConfig());
  }
  return globalForDb.triagePoolV2;
}
