import { useState, type FormEvent } from 'react'
import type { SupabaseClient } from '@supabase/supabase-js'
import { ArrowRight, BarChart3, Check, Eye, EyeOff, LoaderCircle, MessageSquareText } from 'lucide-react'

export function AuthScreen({ supabase }: { supabase: SupabaseClient }) {
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [confirmation, setConfirmation] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setLoading(true)
    setError('')
    setConfirmation(false)
    try {
      if (mode === 'signin') {
        const { error: authError } = await supabase.auth.signInWithPassword({ email, password })
        if (authError) throw authError
      } else {
        const { data, error: authError } = await supabase.auth.signUp({
          email,
          password,
          options: { data: { full_name: name } },
        })
        if (authError) throw authError
        if (!data.session) setConfirmation(true)
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-story">
        <div className="auth-brand"><span className="brand-icon"><MessageSquareText size={20} /></span> Product Voice</div>
        <div className="story-copy">
          <div className="eyebrow light"><span /> Voice-of-customer intelligence</div>
          <h1>Build what your<br />customers are <em>asking for.</em></h1>
          <p>Turn thousands of real conversations into a clear, prioritized product roadmap.</p>
          <div className="story-proof">
            <div className="proof-card proof-main">
              <div className="proof-head"><span>Customer sentiment</span><span className="live-dot">Live</span></div>
              <div className="mini-chart">
                {[36, 48, 43, 63, 55, 74, 69, 87].map((height, index) => <i key={index} style={{ height: `${height}%` }} />)}
              </div>
              <div className="proof-foot"><strong>+18.4%</strong><span>Positive sentiment this quarter</span></div>
            </div>
            <div className="proof-card proof-float">
              <div className="float-icon"><BarChart3 size={18} /></div>
              <div><strong>Checkout friction</strong><span>Emerging issue · 84 mentions</span></div>
            </div>
          </div>
        </div>
        <div className="story-footer">Trusted insights. Real customer voices. Better products.</div>
      </section>

      <section className="auth-form-side">
        <div className="auth-mobile-brand"><span className="brand-icon"><MessageSquareText size={20} /></span> Product Voice</div>
        <div className="auth-card">
          <div className="auth-heading">
            <span className="section-kicker">{mode === 'signin' ? 'Welcome back' : 'Start listening'}</span>
            <h2>{mode === 'signin' ? 'Sign in to your workspace' : 'Create your account'}</h2>
            <p>{mode === 'signin' ? 'Your customer insights are waiting.' : 'Your first customer insight is minutes away.'}</p>
          </div>
          <div className="auth-tabs" role="tablist">
            <button className={mode === 'signin' ? 'active' : ''} onClick={() => { setMode('signin'); setError('') }}>Sign in</button>
            <button className={mode === 'signup' ? 'active' : ''} onClick={() => { setMode('signup'); setError('') }}>Create account</button>
          </div>

          {confirmation ? (
            <div className="confirmation-state">
              <span><Check size={24} /></span><h3>Check your inbox</h3>
              <p>We sent a confirmation link to <strong>{email}</strong>.</p>
              <button className="text-button" onClick={() => { setConfirmation(false); setMode('signin') }}>Back to sign in</button>
            </div>
          ) : (
            <form onSubmit={submit} className="auth-form">
              {mode === 'signup' && <label>Full name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Alex Morgan" required /></label>}
              <label>Work email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" required autoComplete="email" /></label>
              <label>Password<div className="password-field"><input type={showPassword ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={mode === 'signup' ? 'At least 8 characters' : 'Your password'} minLength={8} required autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} /><button type="button" aria-label="Toggle password visibility" onClick={() => setShowPassword(!showPassword)}>{showPassword ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></label>
              {error && <div className="form-error">{error}</div>}
              <button className="primary auth-submit" disabled={loading}>{loading ? <LoaderCircle className="spin" size={19} /> : <>{mode === 'signin' ? 'Sign in' : 'Create workspace'} <ArrowRight size={18} /></>}</button>
              <p className="terms">By continuing, you agree to our Terms and Privacy Policy.</p>
            </form>
          )}
        </div>
      </section>
    </main>
  )
}
