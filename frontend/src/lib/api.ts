import type { Analytics, IngestionJob, IngestResult, Organization, Product, ProductComment, PublicConfig } from '../types'

const API_BASE = import.meta.env.VITE_API_URL || '/api'

async function request<T>(path: string, token?: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || `Request failed with status ${response.status}`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  publicConfig: () => request<PublicConfig>('/config/public'),
  organizations: (token: string) => request<Organization[]>('/organizations', token),
  createOrganization: (token: string, name: string) => request<Organization>('/organizations', token, { method: 'POST', body: JSON.stringify({ name }) }),
  products: (token: string, organizationId: string) => request<Product[]>(`/organizations/${organizationId}/products`, token),
  createProduct: (token: string, organizationId: string, data: { name: string; youtube_query?: string }) => request<Product>(`/organizations/${organizationId}/products`, token, { method: 'POST', body: JSON.stringify(data) }),
  deleteProduct: (token: string, productId: string) => request<void>(`/products/${productId}`, token, { method: 'DELETE' }),
  analytics: (token: string, productId: string, since?: string, sources?: string) => {
    const params = new URLSearchParams()
    if (since) params.set('since', since)
    if (sources) params.set('sources', sources)
    const query = params.size ? `?${params}` : ''
    return request<Analytics>(`/products/${productId}/analytics${query}`, token)
  },
  comments: (token: string, productId: string, search = '', complaintsOnly = false, sources = '', limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (search) params.set('q', search)
    if (complaintsOnly) params.set('complaints_only', 'true')
    if (sources) params.set('sources', sources)
    return request<ProductComment[]>(`/products/${productId}/comments?${params}`, token)
  },
  ingestions: (token: string, productId: string) => request<IngestionJob[]>(`/products/${productId}/ingestions`, token),
  ingest: (token: string, productId: string, data: { depth: 'quick' | 'standard' | 'deep' }) => request<IngestResult>(`/products/${productId}/ingestions`, token, { method: 'POST', body: JSON.stringify(data) }),
  voiceConfig: () => request<{ configured: boolean }>('/voice/config'),
  voiceSignedUrl: (token: string, productId: string) => request<{ signed_url: string; scope_token: string; product_name: string }>(`/voice/products/${productId}/signed-url`, token, { method: 'POST' }),
  voices: (token: string) => request<{ voices: { voice_id: string; name: string }[] }>('/voice/voices', token),
}
