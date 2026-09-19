import { useCallback, useEffect, useState, type FormEvent } from 'react'
import type { Session, SupabaseClient } from '@supabase/supabase-js'
import {
  AlertTriangle, ArrowUpRight, BarChart3, Bell, ChevronDown,
  CirclePlus, Filter, Gauge, Heart, Inbox, Layers3, LoaderCircle,
  LogOut, Menu, MessageCircleWarning, MessageSquareText, MoreHorizontal,
  Plus, RefreshCw, Search, Settings, Sparkles, ThumbsUp, Trash2, TriangleAlert, Users, X,
} from 'lucide-react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '../lib/api'
import type { Analytics, Organization, Product, ProductComment } from '../types'

const SENTIMENT_COLORS: Record<string, string> = {
  positive: '#36a176', neutral: '#c8c9c2', negative: '#e16b5b',
}

interface DashboardProps {
  session: Session
  supabase: SupabaseClient
  notify: (message: string, tone?: 'success' | 'error') => void
}

export function Dashboard({ session, supabase, notify }: DashboardProps) {
  const token = session.access_token
  const [organization, setOrganization] = useState<Organization | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [product, setProduct] = useState<Product | null>(null)
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [comments, setComments] = useState<ProductComment[]>([])
  const [loading, setLoading] = useState(true)
  const [dataLoading, setDataLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [complaintsOnly, setComplaintsOnly] = useState(false)
  const [showAddProduct, setShowAddProduct] = useState(false)
  const [showIngest, setShowIngest] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Product | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [mobileNav, setMobileNav] = useState(false)

  const loadOrganizations = useCallback(async () => {
    setLoading(true)
    try {
      const rows = await api.organizations(token)
      setOrganization((current) => rows.find((item) => item.id === current?.id) || rows[0] || null)
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Could not load organizations', 'error')
    } finally {
      setLoading(false)
    }
  }, [token, notify])

  const loadProducts = useCallback(async (org: Organization) => {
    try {
      const rows = await api.products(token, org.id)
      setProducts(rows)
      setProduct((current) => rows.find((item) => item.id === current?.id) || rows[0] || null)
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Could not load products', 'error')
    }
  }, [token, notify])

  const loadProductData = useCallback(async (selected: Product) => {
    setDataLoading(true)
    try {
      const [insights, feedback] = await Promise.all([
        api.analytics(token, selected.id),
        api.comments(token, selected.id, search, complaintsOnly),
      ])
      setAnalytics(insights)
      setComments(feedback)
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Could not load product insights', 'error')
    } finally {
      setDataLoading(false)
    }
  }, [token, search, complaintsOnly, notify])

  // These effects deliberately hydrate state from external APIs.
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => { void loadOrganizations() }, [loadOrganizations])
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => { if (organization) void loadProducts(organization) }, [organization, loadProducts])
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => {
    if (!product) return
    const timer = window.setTimeout(() => void loadProductData(product), 250)
    return () => window.clearTimeout(timer)
  }, [product, loadProductData])

  async function createWorkspace(companyName: string, productName: string, query: string) {
    const org = await api.createOrganization(token, companyName)
    const created = await api.createProduct(token, org.id, { name: productName, youtube_query: query || undefined })
    setOrganization(org)
    setProducts([created])
    setProduct(created)
    notify('Workspace created')
  }

  async function createProduct(name: string, query: string) {
    if (!organization) return
    const created = await api.createProduct(token, organization.id, { name, youtube_query: query || undefined })
    setProducts((items) => [...items, created])
    setProduct(created)
    setShowAddProduct(false)
    notify(`${name} added`)
  }

  async function removeProduct(target: Product) {
    setDeleting(true)
    try {
      await api.deleteProduct(token, target.id)
      const remaining = products.filter((item) => item.id !== target.id)
      setProducts(remaining)
      // If the deleted product was selected, fall back to another one and
      // clear its data so the dashboard never shows a dead product's numbers.
      if (product?.id === target.id) {
        setProduct(remaining[0] || null)
        setAnalytics(null)
        setComments([])
      }
      setDeleteTarget(null)
      notify(`${target.name} deleted`)
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Could not delete product', 'error')
    } finally {
      setDeleting(false)
    }
  }

  if (loading) return <FullPageLoader />
  if (!organization) return <WorkspaceOnboarding onCreate={createWorkspace} onSignOut={() => supabase.auth.signOut()} />

  return (
    <div className="dashboard-shell">
      <aside className={`sidebar ${mobileNav ? 'open' : ''}`}>
        <div className="sidebar-brand"><span className="brand-icon"><MessageSquareText size={19} /></span><span>Product Voice</span><button className="mobile-close" onClick={() => setMobileNav(false)}><X size={20} /></button></div>
        <div className="workspace-select">
          <div className="workspace-avatar">{organization.name.slice(0, 2).toUpperCase()}</div>
          <div><strong>{organization.name}</strong><span>Workspace</span></div><ChevronDown size={16} />
        </div>
        <nav className="main-nav">
          <span className="nav-label">Workspace</span>
          <a className="active"><BarChart3 size={18} /> Overview</a>
          <a><Sparkles size={18} /> Insights <span className="nav-badge">12</span></a>
          <a><Inbox size={18} /> Feedback</a>
          <span className="nav-label product-label">Products <button onClick={() => setShowAddProduct(true)} aria-label="Add product"><Plus size={15} /></button></span>
          <div className="product-nav">
            {products.map((item, index) => (
              // A row rather than a single button: the delete control cannot
              // be nested inside the select button.
              <div key={item.id} className={`product-nav-row ${item.id === product?.id ? 'active' : ''}`}>
                <button className="product-nav-main" onClick={() => { setProduct(item); setMobileNav(false) }}>
                  <span className={`product-dot color-${index % 4}`} />{item.name}
                </button>
                <button
                  className="product-delete"
                  title={`Delete ${item.name}`}
                  aria-label={`Delete ${item.name}`}
                  onClick={() => setDeleteTarget(item)}
                ><Trash2 size={14} /></button>
              </div>
            ))}
          </div>
        </nav>
        <div className="sidebar-bottom">
          <a><Users size={18} /> Team</a><a><Settings size={18} /> Settings</a>
          <div className="user-row">
            <div className="user-avatar">{initials(session.user.user_metadata?.full_name || session.user.email || 'U')}</div>
            <div><strong>{session.user.user_metadata?.full_name || 'Account'}</strong><span>{session.user.email}</span></div>
            <button onClick={() => supabase.auth.signOut()} title="Sign out"><LogOut size={17} /></button>
          </div>
        </div>
      </aside>
      {mobileNav && <button className="nav-scrim" onClick={() => setMobileNav(false)} />}

      <main className="dashboard-main">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setMobileNav(true)}><Menu size={22} /></button>
          <div className="breadcrumb"><span>{organization.name}</span><b>/</b><strong>{product?.name || 'Products'}</strong></div>
          <div className="topbar-actions"><button className="icon-button"><Bell size={19} /><i /></button><button className="secondary" onClick={() => setShowAddProduct(true)}><CirclePlus size={17} /> Add product</button></div>
        </header>

        {!product ? (
          <EmptyProducts onAdd={() => setShowAddProduct(true)} />
        ) : (
          <div className="dashboard-content">
            <section className="page-heading">
              <div><div className="eyebrow"><span /> Product intelligence</div><h1>{product.name}</h1><p>What customers are saying across your public feedback sources.</p></div>
              <div className="heading-actions">
                {products.length > 1 && (
                  <label className="product-switch">
                    <Layers3 size={15} />
                    <select value={product.id} onChange={(e) => { const next = products.find((p) => p.id === e.target.value); if (next) setProduct(next) }}>
                      {products.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                    </select>
                    <ChevronDown size={15} />
                  </label>
                )}
                <button className="secondary" onClick={() => void loadProductData(product)}><RefreshCw size={17} className={dataLoading ? 'spin' : ''} /> Refresh</button>
                <button className="primary" onClick={() => setShowIngest(true)}><Sparkles size={17} /> Collect feedback</button>
              </div>
            </section>
            {dataLoading && !analytics ? <DashboardSkeleton /> : analytics && <AnalyticsView analytics={analytics} comments={comments} search={search} setSearch={setSearch} complaintsOnly={complaintsOnly} setComplaintsOnly={setComplaintsOnly} />}
          </div>
        )}
      </main>

      {showAddProduct && <ProductModal onClose={() => setShowAddProduct(false)} onSubmit={createProduct} />}
      {deleteTarget && <DeleteProductModal product={deleteTarget} busy={deleting} onCancel={() => setDeleteTarget(null)} onConfirm={() => void removeProduct(deleteTarget)} />}
      {showIngest && product && <IngestModal product={product} token={token} onClose={() => setShowIngest(false)} onComplete={(message) => { setShowIngest(false); notify(message); void loadProductData(product) }} />}
    </div>
  )
}

function AnalyticsView({ analytics, comments, search, setSearch, complaintsOnly, setComplaintsOnly }: {
  analytics: Analytics; comments: ProductComment[]; search: string; setSearch: (value: string) => void; complaintsOnly: boolean; setComplaintsOnly: (value: boolean) => void
}) {
  const sentimentData = ['positive', 'neutral', 'negative'].map((name) => ({ name, value: analytics.sentiment.find((item) => item.name === name)?.count || 0 }))
  const trendData = analytics.timeline.map((item) => ({ ...item, label: new Date(item.month).toLocaleDateString('en-US', { month: 'short', year: '2-digit' }) }))
  const issueData = analytics.issues.slice(0, 7).map((item) => ({ ...item, label: titleCase(item.name) }))
  const topIssue = analytics.issues[0]
  const issueTotal = analytics.issues.reduce((sum, item) => sum + item.count, 0)
  const health = analytics.average_sentiment == null ? 'No signal yet' : analytics.average_sentiment >= .25 ? 'Healthy' : analytics.average_sentiment >= 0 ? 'Mixed' : 'At risk'

  return <>
    <section className="insight-banner">
      <div className="insight-spark"><Sparkles size={20} /></div>
      <div><span>AI insight</span><strong>{topIssue ? `${titleCase(topIssue.name)} is the leading conversation theme` : 'Collect more feedback to uncover customer themes'}</strong><p>{topIssue ? `${topIssue.count} mentions account for ${Math.round((topIssue.count / Math.max(issueTotal, 1)) * 100)}% of classified issue signals.` : 'Once comments arrive, Product Voice will surface recurring problems and customer needs.'}</p></div>
      {topIssue && <button>Explore theme <ArrowUpRight size={16} /></button>}
    </section>

    <section className="metric-grid">
      <MetricCard icon={<MessageSquareText />} label="Total conversations" value={compact(analytics.total)} detail={`Across ${analytics.by_source.length} source${analytics.by_source.length === 1 ? '' : 's'}`} tone="violet" />
      <MetricCard icon={<MessageCircleWarning />} label="Complaint rate" value={`${(analytics.complaint_rate * 100).toFixed(1)}%`} detail={`${analytics.complaints} complaints detected`} tone="coral" />
      <MetricCard icon={<Gauge />} label="Customer health" value={health} detail={`Sentiment score ${formatScore(analytics.average_sentiment)}`} tone="green" />
      <MetricCard icon={<Heart />} label="Distinct voices" value={compact(analytics.distinct_authors)} detail="Unique authors, deduplicated" tone="amber" />
    </section>

    <section className="chart-grid">
      <div className="panel trend-panel">
        <PanelHeader title="Conversation volume" subtitle="Monthly customer feedback" />
        <div className="chart-wrap">
          {trendData.length ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={trendData} margin={{ top: 15, right: 12, left: -22, bottom: 0 }}><defs><linearGradient id="volumeFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6858d9" stopOpacity={.28}/><stop offset="100%" stopColor="#6858d9" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="#ecece7" vertical={false}/><XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#898a83', fontSize: 11 }} minTickGap={24}/><YAxis tickLine={false} axisLine={false} tick={{ fill: '#898a83', fontSize: 11 }}/><Tooltip contentStyle={{ border: '1px solid #e4e5df', borderRadius: 10, boxShadow: '0 8px 24px rgba(24,25,23,.08)' }}/><Area type="monotone" dataKey="count" stroke="#6858d9" strokeWidth={2.5} fill="url(#volumeFill)" activeDot={{ r: 5, fill: '#6858d9', stroke: '#fff', strokeWidth: 3 }} isAnimationActive={false}/></AreaChart></ResponsiveContainer> : <NoChartData />}
        </div>
      </div>
      <div className="panel sentiment-panel">
        <PanelHeader title="Sentiment mix" subtitle="How customers feel" />
        <div className="sentiment-content">
          <div className="donut-wrap"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={sentimentData} dataKey="value" innerRadius={58} outerRadius={78} paddingAngle={3} stroke="none" isAnimationActive={false}>{sentimentData.map((entry) => <Cell key={entry.name} fill={SENTIMENT_COLORS[entry.name]} />)}</Pie></PieChart></ResponsiveContainer><div className="donut-center"><strong>{analytics.total ? Math.round((sentimentData[0].value / analytics.total) * 100) : 0}%</strong><span>positive</span></div></div>
          <div className="sentiment-legend">{sentimentData.map((entry) => <div key={entry.name}><i style={{ background: SENTIMENT_COLORS[entry.name] }} /><span>{titleCase(entry.name)}</span><strong>{entry.value}</strong></div>)}</div>
        </div>
      </div>
    </section>

    <section className="chart-grid lower-grid">
      <div className="panel issues-panel">
        <PanelHeader title="Top customer issues" subtitle="Recurring themes across feedback" />
        <div className="issues-chart">{issueData.length ? <ResponsiveContainer width="100%" height="100%"><BarChart data={issueData} layout="vertical" margin={{ left: 4, right: 28 }}><CartesianGrid stroke="#f0f0eb" horizontal={false}/><XAxis type="number" hide/><YAxis type="category" dataKey="label" axisLine={false} tickLine={false} width={105} tick={{ fill: '#65675f', fontSize: 12 }}/><Tooltip cursor={{ fill: '#f6f6f2' }} contentStyle={{ border: '1px solid #e4e5df', borderRadius: 10 }}/><Bar dataKey="count" fill="#8172df" radius={[0, 5, 5, 0]} barSize={16} isAnimationActive={false}/></BarChart></ResponsiveContainer> : <NoChartData />}</div>
      </div>
      <div className="panel sources-panel">
        <PanelHeader title="Source breakdown" subtitle="Totals pool these — the mix matters" />
        <div className="source-list">{analytics.by_source.length ? analytics.by_source.map((row, index) => <div className="source-row" key={row.source}><span className="source-rank">{String(index + 1).padStart(2, '0')}</span><div><strong>{titleCase(row.source)}</strong><span>{compact(row.count)} items · {Math.round(row.share * 100)}% of corpus · {(row.complaint_rate * 100).toFixed(0)}% complaints · {formatScore(row.average_sentiment)} sentiment</span></div></div>) : <div className="empty-small"><Layers3 size={22} /><span>No sources collected yet</span></div>}</div>
      </div>
    </section>

    <section className="panel feedback-panel">
      <div className="feedback-head"><PanelHeader title="Customer conversations" subtitle="Search the feedback behind every insight" /><div className="feedback-tools"><label className="search-box"><Search size={16} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search comments…" /></label><button className={complaintsOnly ? 'filter-button active' : 'filter-button'} onClick={() => setComplaintsOnly(!complaintsOnly)}><Filter size={16} /> Complaints</button></div></div>
      <div className="comment-list">{comments.length ? comments.map((comment) => <article className="comment-row" key={`${comment.source}-${comment.external_id}`}><div className={`sentiment-avatar ${comment.sentiment || 'neutral'}`}>{comment.sentiment === 'positive' ? <ThumbsUp size={17} /> : comment.sentiment === 'negative' ? <AlertTriangle size={17} /> : <MessageSquareText size={17} />}</div><div className="comment-body"><div className="comment-meta"><span className="source-chip">{titleCase(comment.source)}</span><strong>{String(comment.source_metadata?.thread_title || comment.content_type)}</strong><time>{comment.published_at ? relativeDate(comment.published_at) : ''}</time></div><p>{comment.content}</p><div className="comment-tags">{comment.issue_categories.map((tag) => <span key={tag}>{titleCase(tag)}</span>)}{comment.is_complaint && <span className="complaint-tag">Complaint</span>}{comment.relevant === false && <span className="offtopic-tag">Off-topic</span>}</div></div>{comment.url ? <a className="comment-likes" href={comment.url} target="_blank" rel="noreferrer"><ThumbsUp size={14} /> {comment.engagement?.score ?? 0}</a> : <div className="comment-likes"><ThumbsUp size={14} /> {comment.engagement?.score ?? 0}</div>}</article>) : <div className="empty-feedback"><Search size={28} /><strong>No conversations found</strong><span>Try a different search or collect more feedback.</span></div>}</div>
    </section>
  </>
}

function MetricCard({ icon, label, value, detail, tone }: { icon: React.ReactNode; label: string; value: string; detail: string; tone: string }) {
  return <div className="metric-card"><div className={`metric-icon ${tone}`}>{icon}</div><div className="metric-label">{label}<button><MoreHorizontal size={17} /></button></div><strong className="metric-value">{value}</strong><span className="metric-detail">{detail}</span></div>
}

function PanelHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return <div className="panel-header"><div><h2>{title}</h2><p>{subtitle}</p></div><button><MoreHorizontal size={18} /></button></div>
}

function WorkspaceOnboarding({ onCreate, onSignOut }: { onCreate: (company: string, product: string, query: string) => Promise<void>; onSignOut: () => void }) {
  const [company, setCompany] = useState('')
  const [product, setProduct] = useState('')
  const [query, setQuery] = useState('')
  const [step, setStep] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  async function submit(event: FormEvent) { event.preventDefault(); if (step === 1) { setStep(2); return } setLoading(true); setError(''); try { await onCreate(company, product, query) } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not create workspace') } finally { setLoading(false) } }
  return <main className="onboarding-page"><div className="onboarding-top"><div className="auth-brand dark"><span className="brand-icon"><MessageSquareText size={20}/></span> Product Voice</div><button onClick={onSignOut}>Sign out</button></div><form className="onboarding-card" onSubmit={submit}><div className="step-track"><span className="active"/><span className={step === 2 ? 'active' : ''}/></div><div className="onboarding-icon">{step === 1 ? <Users size={25}/> : <Layers3 size={25}/>}</div><span className="section-kicker">Step {step} of 2</span><h1>{step === 1 ? 'Name your workspace' : 'Add your first product'}</h1><p>{step === 1 ? 'Usually your company or team name.' : 'Choose a product and the search query we should monitor.'}</p>{step === 1 ? <label>Workspace name<input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Acme Product Team" autoFocus required/></label> : <><label>Product name<input value={product} onChange={(e) => setProduct(e.target.value)} placeholder="Acme Mobile" autoFocus required/></label><label>Search query <span>Optional</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`${product || 'Product'} review`}/></label></>}{error && <div className="form-error">{error}</div>}<button className="primary" disabled={loading}>{loading ? <LoaderCircle className="spin" size={19}/> : step === 1 ? 'Continue' : 'Create workspace'} {!loading && <ArrowUpRight size={18}/>}</button>{step === 2 && <button type="button" className="text-button" onClick={() => setStep(1)}>Back</button>}</form></main>
}

function DeleteProductModal({ product, busy, onCancel, onConfirm }: {
  product: Product; busy: boolean; onCancel: () => void; onConfirm: () => void
}) {
  return <Modal title={`Delete ${product.name}?`} subtitle="This cannot be undone." onClose={onCancel}>
    <div className="danger-body">
      <div className="danger-icon"><TriangleAlert size={21} /></div>
      <p>
        This permanently deletes <strong>{product.name}</strong> and every piece of
        feedback collected for it. Other products are not affected.
      </p>
    </div>
    <div className="modal-actions">
      <button type="button" className="secondary" onClick={onCancel} disabled={busy}>Cancel</button>
      <button type="button" className="danger" onClick={onConfirm} disabled={busy}>
        {busy ? <><LoaderCircle className="spin" size={18} /> Deleting…</> : <><Trash2 size={17} /> Delete product</>}
      </button>
    </div>
  </Modal>
}


function ProductModal({ onClose, onSubmit }: { onClose: () => void; onSubmit: (name: string, query: string) => Promise<void> }) {
  const [name, setName] = useState(''); const [query, setQuery] = useState(''); const [loading, setLoading] = useState(false); const [error, setError] = useState('')
  async function submit(event: FormEvent) { event.preventDefault(); setLoading(true); setError(''); try { await onSubmit(name, query) } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not add product'); setLoading(false) } }
  return <Modal title="Add a product" subtitle="Start tracking customer conversations." onClose={onClose}><form className="modal-form" onSubmit={submit}><label>Product name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. iPhone 18" autoFocus required/></label><label>Search query <span>Optional</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`${name || 'Product'} review`}/></label>{error && <div className="form-error">{error}</div>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button className="primary" disabled={loading}>{loading ? <LoaderCircle className="spin" size={18}/> : <Plus size={18}/>} Add product</button></div></form></Modal>
}

function IngestModal({ product, token, onClose, onComplete }: { product: Product; token: string; onClose: () => void; onComplete: (message: string) => void }) {
  const [depth, setDepth] = useState<'quick' | 'standard' | 'deep'>('standard')
  const [loading, setLoading] = useState(false); const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault(); setLoading(true); setError('')
    try {
      const result = await api.ingest(token, product.id, { depth })
      const ok = result.sources.filter((s) => s.status === 'ok')
      onComplete(`${result.documents_indexed} items indexed from ${ok.length} source${ok.length === 1 ? '' : 's'}`)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Collection failed'); setLoading(false) }
  }
  const DEPTHS = [
    { id: 'quick' as const, label: 'Quick', detail: 'Fewer items, fastest. Skips the AI source planner.' },
    { id: 'standard' as const, label: 'Standard', detail: 'Recommended. AI picks the sources and writes the queries.' },
    { id: 'deep' as const, label: 'Deep', detail: 'Largest corpus. Takes noticeably longer.' },
  ]
  return <Modal title={`Collect feedback for ${product.name}`} subtitle="Searches every available source and indexes the results" onClose={onClose}>
    <form className="modal-form" onSubmit={submit}>
      <div className="depth-options">{DEPTHS.map((option) => (
        <label key={option.id} className={depth === option.id ? 'depth-option active' : 'depth-option'}>
          <input type="radio" name="depth" value={option.id} checked={depth === option.id} onChange={() => setDepth(option.id)} />
          <span><strong>{option.label}</strong><small>{option.detail}</small></span>
        </label>
      ))}</div>
      <div className="quota-note"><Gauge size={17} /><span>Sources without credentials are skipped and reported, never fatal.</span></div>
      {error && <div className="form-error">{error}</div>}
      <div className="modal-actions">
        <button type="button" className="secondary" onClick={onClose} disabled={loading}>Cancel</button>
        <button className="primary" disabled={loading}>{loading ? <><LoaderCircle className="spin" size={18} /> Collecting…</> : <><Sparkles size={18} /> Collect feedback</>}</button>
      </div>
    </form>
  </Modal>
}

function Modal({ title, subtitle, onClose, children }: { title: string; subtitle: string; onClose: () => void; children: React.ReactNode }) { return <div className="modal-backdrop" role="presentation"><div className="modal" role="dialog" aria-modal="true"><button className="modal-close" onClick={onClose}><X size={20}/></button><h2>{title}</h2><p>{subtitle}</p>{children}</div></div> }
function EmptyProducts({ onAdd }: { onAdd: () => void }) { return <div className="center-empty"><div className="empty-illustration"><Layers3 size={32}/></div><h1>Add your first product</h1><p>Connect a product to begin turning customer conversations into insights.</p><button className="primary" onClick={onAdd}><Plus size={18}/> Add product</button></div> }
function NoChartData() { return <div className="no-chart"><BarChart3 size={25}/><span>Collect feedback to populate this chart</span></div> }
function FullPageLoader() { return <div className="full-loader"><span className="brand-icon"><MessageSquareText size={20}/></span><LoaderCircle className="spin" size={24}/></div> }
function DashboardSkeleton() { return <div className="skeleton-grid">{Array.from({ length: 8 }).map((_, index) => <div key={index}/>)}</div> }
function compact(value: number) { return new Intl.NumberFormat('en', { notation: value > 999 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value) }
function titleCase(value: string) { return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()) }
function initials(value: string) { return value.split(/\s|@/).filter(Boolean).slice(0, 2).map((item) => item[0]).join('').toUpperCase() }
function formatScore(value: number | null) { return value == null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}` }
function relativeDate(value: string) { const days = Math.floor((Date.now() - new Date(value).getTime()) / 86400000); return days <= 0 ? 'Today' : days === 1 ? 'Yesterday' : days < 30 ? `${days}d ago` : new Date(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) }
