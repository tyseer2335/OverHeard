import { useCallback, useEffect, useState } from 'react'
import type { Session, SupabaseClient } from '@supabase/supabase-js'
import { AlertCircle, CheckCircle2, LoaderCircle, MessageSquareText, X } from 'lucide-react'
import { AuthScreen } from './components/AuthScreen'
import { Dashboard } from './components/Dashboard'
import { getSupabase } from './lib/supabase'
import './App.css'

interface ToastState { id: number; message: string; tone: 'success' | 'error' }

function App() {
  const [supabase, setSupabase] = useState<SupabaseClient | null>(null)
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [fatalError, setFatalError] = useState('')
  const [toasts, setToasts] = useState<ToastState[]>([])

  useEffect(() => {
    let active = true
    let unsubscribe: (() => void) | undefined
    getSupabase().then(async (client) => {
      if (!active) return
      setSupabase(client)
      const { data } = await client.auth.getSession()
      if (active) { setSession(data.session); setLoading(false) }
      const listener = client.auth.onAuthStateChange((_event, nextSession) => {
        if (active) setSession(nextSession)
      })
      unsubscribe = () => listener.data.subscription.unsubscribe()
    }).catch((error) => {
      if (active) {
        setFatalError(error instanceof Error ? error.message : 'Could not start the application')
        setLoading(false)
      }
    })
    return () => { active = false; unsubscribe?.() }
  }, [])

  const notify = useCallback((message: string, tone: 'success' | 'error' = 'success') => {
    const id = Date.now()
    setToasts((items) => [...items, { id, message, tone }])
    window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 4200)
  }, [])

  if (loading) return <div className="full-loader"><span className="brand-icon"><MessageSquareText size={20}/></span><LoaderCircle className="spin" size={25}/></div>
  if (fatalError || !supabase) return <div className="fatal-state"><AlertCircle size={32}/><h1>Couldn’t connect</h1><p>{fatalError || 'Supabase configuration is unavailable.'}</p><button className="primary" onClick={() => window.location.reload()}>Try again</button></div>

  return <>
    {session ? <Dashboard session={session} supabase={supabase} notify={notify} /> : <AuthScreen supabase={supabase} />}
    <div className="toast-stack">{toasts.map((toast) => <div className={`toast ${toast.tone}`} key={toast.id}>{toast.tone === 'success' ? <CheckCircle2 size={18}/> : <AlertCircle size={18}/>}<span>{toast.message}</span><button onClick={() => setToasts((items) => items.filter((item) => item.id !== toast.id))}><X size={15}/></button></div>)}</div>
  </>
}

export default App
