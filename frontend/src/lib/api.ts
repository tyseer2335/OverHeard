import type { Analytics, IngestResult, Organization, Product, ProductComment, PublicConfig } from '../types'

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
  return response.json() as Promise<T>
}

export const api = {
  publicConfig: () => request<PublicConfig>('/config/public'),
  organizations: (token: string) => request<Organization[]>('/organizations', token),
  createOrganization: (token: string, name: string) => request<Organization>('/organizations', token, { method: 'POST', body: JSON.stringify({ name }) }),
  products: (token: string, organizationId: string) => request<Product[]>(`/organizations/${organizationId}/products`, token),
  createProduct: (token: string, organizationId: string, data: { name: string; youtube_query?: string }) => request<Product>(`/organizations/${organizationId}/products`, token, { method: 'POST', body: JSON.stringify(data) }),
  analytics: (token: string, productId: string) => request<Analytics>(`/products/${productId}/analytics`, token),
  comments: (token: string, productId: string, search = '', complaintsOnly = false) => {
    const params = new URLSearchParams({ limit: '40' })
    if (search) params.set('q', search)
    if (complaintsOnly) params.set('complaints_only', 'true')
    return request<ProductComment[]>(`/products/${productId}/comments?${params}`, token)
  },
  ingest: (token: string, productId: string, data: { max_videos: number; max_comments_per_video: number; include_replies: boolean }) => request<IngestResult>(`/products/${productId}/ingestions`, token, { method: 'POST', body: JSON.stringify(data) }),
}
