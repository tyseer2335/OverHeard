import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import { api } from './api'

let clientPromise: Promise<SupabaseClient> | undefined

export function getSupabase(): Promise<SupabaseClient> {
  if (!clientPromise) {
    clientPromise = api.publicConfig().then((config) => createClient(
      config.supabase_url,
      config.supabase_publishable_key,
      { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } },
    ))
  }
  return clientPromise
}
