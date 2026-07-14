const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`
  return `${API_BASE}${normalizedPath}`
}

export function apiRootUrl(path: string): string {
  const rootBase = API_BASE.endsWith("/api") ? API_BASE.slice(0, -4) : API_BASE
  const normalizedPath = path.startsWith("/") ? path : `/${path}`
  return `${rootBase}${normalizedPath}`
}
