/**
 * Single source of truth for the backend base URL.
 *
 * The backend exposes two families of routes: everything under `/api/...`, and
 * the top-level routers (`/lesson-intelligence`, `/teaching-intelligence`,
 * `/phase2`). `NEXT_PUBLIC_API_URL` points at the `/api` prefix, so root-level
 * routes are built by stripping it back off.
 */

const RAW_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"

/** Base for `/api/...` routes, without a trailing slash. */
export const API_BASE = RAW_BASE.replace(/\/+$/, "")

/**
 * Origin the API is served from, without the `/api` suffix.
 *
 * Anchored to the end of the string on purpose — a plain `replace("/api", "")`
 * would corrupt a host such as `https://api.example.com/api`.
 */
export const API_ROOT = API_BASE.replace(/\/api$/, "")

function join(base: string, path: string): string {
  return `${base}${path.startsWith("/") ? path : `/${path}`}`
}

/** Build a URL for a route under `/api`. */
export function apiUrl(path: string): string {
  return join(API_BASE, path)
}

/** Build a URL for a route mounted at the server root. */
export function apiRootUrl(path: string): string {
  return join(API_ROOT, path)
}
