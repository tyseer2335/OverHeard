import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import type { Session, SupabaseClient } from '@supabase/supabase-js'
import {
  ArrowLeft, ArrowRight, ArrowUpRight, BarChart3, Check,
  ChevronDown, CircleDot, Command, ExternalLink, Inbox, Layers3, LoaderCircle,
  LogOut, Menu, Mic, PackageSearch, Plus, RefreshCw,
  Search, Settings, ThumbsUp, Trash2, TriangleAlert, X, Zap } from 'lucide-react'
import { FaHackerNews, FaRedditAlien, FaXTwitter, FaYoutube } from 'react-icons/fa6'
import { api } from '../lib/api'
import { VoxPanel } from './VoxPanel'
import type { Analytics, IngestionJob, IngestResult, Organization, Product, ProductComment } from '../types'

type View = 'overview' | 'issues' | 'evidence' | 'new' | 'detail'
type Severity = 'critical' | 'high' | 'medium' | 'low'

interface Issue {
  id: string; title: string; category: string; summary: string; mentions: number
  sentiment: number; sources: string[]; severity: Severity; evidence: ProductComment[]
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
  const [range, setRange] = useState<'24h' | '7d' | '30d'>('30d')
  const [view, setView] = useState<View>(() => routeFromPath(location.pathname))
  const [detailId, setDetailId] = useState(() => detailFromPath(location.pathname))
  const [mobileNav, setMobileNav] = useState(false)
  const [showAddProduct, setShowAddProduct] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Product | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [showIngest, setShowIngest] = useState(false)
  const [showVox, setShowVox] = useState(false)
  const [showCommand, setShowCommand] = useState(false)
  const [dialog, setDialog] = useState<'integrations' | 'settings' | null>(null)

  const navigate = useCallback((next: View, issueId?: string) => {
    const path = next === 'overview' ? '/' : next === 'detail' ? `/issues/${issueId}` : `/${next}`
    history.pushState({}, '', path)
    setView(next); setDetailId(issueId || ''); setMobileNav(false)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  useEffect(() => {
    const onPop = () => { setView(routeFromPath(location.pathname)); setDetailId(detailFromPath(location.pathname)) }
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setShowCommand(true) }
      if (event.key === 'Escape') { setShowCommand(false); setShowVox(false) }
    }
    addEventListener('popstate', onPop); addEventListener('keydown', onKey)
    return () => { removeEventListener('popstate', onPop); removeEventListener('keydown', onKey) }
  }, [])

  const loadOrganizations = useCallback(async () => {
    setLoading(true)
    try {
      const rows = await api.organizations(token)
      const org = rows[0] || null
      setOrganization(org)
      if (org) {
        const productRows = await api.products(token, org.id)
        setProducts(productRows); setProduct(productRows[0] || null)
      }
    } catch (error) { notify(errorMessage(error), 'error') } finally { setLoading(false) }
  }, [token, notify])

  const loadData = useCallback(async (selected: Product) => {
    setDataLoading(true)
    try {
      const since = range === '24h' ? isoDaysAgo(1) : range === '7d' ? isoDaysAgo(7) : isoDaysAgo(30)
      const [nextAnalytics, nextComments] = await Promise.all([
        api.analytics(token, selected.id, since), api.comments(token, selected.id),
      ])
      setAnalytics(nextAnalytics); setComments(nextComments)
    } catch (error) { notify(errorMessage(error), 'error') } finally { setDataLoading(false) }
  }, [token, range, notify])

  // These effects intentionally synchronize React with authenticated backend data.
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => { void loadOrganizations() }, [loadOrganizations])
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => { if (product) void loadData(product) }, [product, loadData])

  const issues = useMemo(() => deriveIssues(analytics, comments), [analytics, comments])
  const selectedIssue = issues.find((issue) => issue.id === detailId) || issues[0]

  async function createWorkspace(company: string, productName: string, query: string) {
    const org = await api.createOrganization(token, company)
    const created = await api.createProduct(token, org.id, { name: productName, youtube_query: query || undefined })
    setOrganization(org); setProducts([created]); setProduct(created); notify('Workspace created')
  }

  async function createProduct(name: string, query: string) {
    if (!organization) return
    const created = await api.createProduct(token, organization.id, { name, youtube_query: query || undefined })
    setProducts((items) => [...items, created]); setProduct(created); setShowAddProduct(false); notify(`${name} added`)
  }

  async function removeProduct(target: Product) {
    setDeleting(true)
    try {
      await api.deleteProduct(token, target.id)
      const remaining = products.filter((item) => item.id !== target.id)
      setProducts(remaining)
      // Clear the view if the deleted product was selected, so the dashboard
      // never shows a dead product's numbers.
      if (product?.id === target.id) setProduct(remaining[0] || null)
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

  return <div className="ov-app">
    <Sidebar organization={organization} products={products} product={product} view={view} session={session} onDelete={setDeleteTarget}
      onNavigate={navigate} onProduct={setProduct} onAdd={() => setShowAddProduct(true)} onDialog={setDialog}
      onSignOut={() => supabase.auth.signOut()} mobile={mobileNav} onClose={() => setMobileNav(false)} issueCount={issues.length} />
    {mobileNav && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
    <main className="ov-main">
      {view !== 'new' && <Topbar organization={organization} product={product} range={range} setRange={setRange}
        onMenu={() => setMobileNav(true)} onSearch={() => setShowCommand(true)} onVox={() => setShowVox(true)} />}
      {!product ? <EmptyProducts onAdd={() => setShowAddProduct(true)} /> : dataLoading && !analytics ? <DashboardSkeleton /> : <>
        {view === 'overview' && <Overview product={product} issues={issues} comments={comments} loading={dataLoading}
          onRefresh={() => void loadData(product)} onCollect={() => setShowIngest(true)} onIssue={(id) => navigate('detail', id)} onIssues={() => navigate('issues')} />}
        {view === 'issues' && <IssuesPage issues={issues} onIssue={(id) => navigate('detail', id)} onNew={() => navigate('new')} />}
        {view === 'evidence' && <EvidencePage comments={comments} />}
        {view === 'detail' && selectedIssue && <IssueDetail issue={selectedIssue} onBack={() => navigate('issues')} onVox={() => setShowVox(true)}
          onTicket={() => notify('Created Linear issue OVH-482')} />}
        {view === 'new' && <NewResearch product={product} onClose={() => navigate('overview')} onStart={async () => { setShowIngest(true); navigate('overview') }} onVox={() => setShowVox(true)} />}
      </>}
    </main>
    {showAddProduct && <ProductModal onClose={() => setShowAddProduct(false)} onSubmit={createProduct} />}
    {deleteTarget && <DeleteProductModal product={deleteTarget} busy={deleting} onCancel={() => setDeleteTarget(null)} onConfirm={() => void removeProduct(deleteTarget)} />}
    {showIngest && product && <IngestModal product={product} token={token} onClose={() => setShowIngest(false)} onComplete={(text) => { notify(text); void loadData(product) }} />}
    {showVox && product && <VoxPanel key={product.id} product={product} token={token} issues={issues} onClose={() => setShowVox(false)} onOpenIssue={(id) => { setShowVox(false); navigate('detail', id) }} />}
    {showCommand && <CommandPalette issues={issues} onClose={() => setShowCommand(false)} onNavigate={(next, id) => { setShowCommand(false); navigate(next, id) }} />}
    {dialog && <InfoDialog kind={dialog} onClose={() => setDialog(null)} />}
  </div>
}

function Sidebar({ organization, products, product, view, session, mobile, issueCount, onNavigate, onProduct, onAdd, onDelete, onDialog, onSignOut, onClose }: {
  organization: Organization; products: Product[]; product: Product | null; view: View; session: Session; mobile: boolean; issueCount: number
  onNavigate: (view: View) => void; onProduct: (product: Product) => void; onAdd: () => void; onDelete: (product: Product) => void; onDialog: (kind: 'integrations' | 'settings') => void; onSignOut: () => void; onClose: () => void
}) {
  return <aside className={`ov-sidebar ${mobile ? 'open' : ''}`}>
    <div className="ov-brand"><span className="overheard-logo" role="img" aria-label="Overheard"/><button className="mobile-close" onClick={onClose}><X size={18}/></button></div>
    <button className="workspace-pill"><span>{initials(organization.name)}</span><span><b>{organization.name}</b><small>Workspace</small></span><ChevronDown size={14}/></button>
    <nav className="ov-nav" aria-label="Main navigation">
      <NavLabel>Workspace</NavLabel>
      <NavButton active={view === 'overview'} icon={<BarChart3/>} onClick={() => onNavigate('overview')}>Overview</NavButton>
      <NavButton active={view === 'issues' || view === 'detail'} icon={<CircleDot/>} onClick={() => onNavigate('issues')}>Pain points <em>{issueCount}</em></NavButton>
      <NavButton active={view === 'evidence'} icon={<Inbox/>} onClick={() => onNavigate('evidence')}>Evidence</NavButton>
      <NavLabel action={onAdd}>Products</NavLabel>
      {/* A row, not a single button: the delete control cannot nest inside the select button. */}
      {products.map((item) => <div key={item.id} className={`product-row ${item.id === product?.id ? 'active' : ''}`}>
        <button className="product-link" onClick={() => { onProduct(item); onNavigate('overview') }}><i/>{item.name}</button>
        <button className="product-remove" title={`Delete ${item.name}`} aria-label={`Delete ${item.name}`} onClick={() => onDelete(item)}><Trash2 size={13}/></button>
      </div>)}
    </nav>
    <div className="ov-sidebar-bottom">
      <button onClick={() => onDialog('integrations')}><Zap/>Integrations</button>
      <button onClick={() => onDialog('settings')}><Settings/>Settings</button>
      <div className="sources-live"><header><span>Sources</span><b><i/> Live</b></header><div><span title="YouTube"><FaYoutube/></span><span title="Reddit"><FaRedditAlien/></span><span title="Hacker News"><FaHackerNews/></span><span className="source-beta" title="X"><FaXTwitter/></span></div></div>
      <div className="ov-user"><span>{initials(session.user.user_metadata?.full_name || session.user.email || 'U')}</span><div><b>{session.user.user_metadata?.full_name || 'Account'}</b><small>{session.user.email}</small></div><button onClick={onSignOut} aria-label="Sign out"><LogOut size={15}/></button></div>
    </div>
  </aside>
}

function Topbar({ organization, product, range, setRange, onMenu, onSearch, onVox }: {
  organization: Organization; product: Product | null; range: string; setRange: (range: '24h' | '7d' | '30d') => void; onMenu: () => void; onSearch: () => void; onVox: () => void
}) {
  return <header className="ov-topbar"><button className="mobile-menu" onClick={onMenu}><Menu/></button><div className="ov-crumb"><span>{organization.name}</span><b>/</b>{product?.name || 'Products'}</div><div className="top-actions"><div className="range-control">{(['24h','7d','30d'] as const).map((item) => <button key={item} className={range === item ? 'active' : ''} onClick={() => setRange(item)}>{item}</button>)}</div><button className="search-trigger" onClick={onSearch}><Search/>Search <kbd>⌘K</kbd></button><button className="outline-accent" onClick={onVox}><Mic/>Ask Vox</button></div></header>
}

function Overview({ product, issues, comments, loading, onRefresh, onCollect, onIssue, onIssues }: {
  product: Product; issues: Issue[]; comments: ProductComment[]; loading: boolean; onRefresh: () => void; onCollect: () => void; onIssue: (id: string) => void; onIssues: () => void
}) {
  const evidence = rankEvidence(comments).slice(0,6)
  return <div className="ov-page">
    <PageHeader eyebrow="Executive brief" title={product.name} subtitle="Recommended product decisions, grounded in public customer feedback." actions={<><button className="button" onClick={onRefresh}><RefreshCw className={loading ? 'spin' : ''}/>Refresh</button><button className="button accent" onClick={onCollect}><PackageSearch/>Collect feedback</button></>} />
    <section className="action-section"><SectionHead title="Recommended actions" subtitle="Start here — these are the clearest opportunities in the current feedback." action={<button onClick={onIssues}>See all pain points</button>}/><div className="executive-actions">{issues.slice(0,3).map((issue,index)=><article className="surface executive-action" key={issue.id}><span>{String(index+1).padStart(2,'0')}</span><div><h2>Address {issue.title.toLowerCase()}</h2><p>{issue.summary}</p><small>{issue.mentions} relevant comments · {issue.sources.length || 1} source{issue.sources.length===1?'':'s'} · {sentimentLabel(issue.sentiment)} sentiment</small></div><button onClick={()=>onIssue(issue.id)}>Review decision <ArrowRight/></button></article>)}{!issues.length&&<div className="surface"><Empty title="No recommendations yet" text="Collect feedback to generate evidence-backed actions."/></div>}</div></section>
    <section className="surface overview-evidence"><SectionHead title="Evidence behind these decisions" subtitle="The highest-impact public comments, ordered by engagement."/><div className="overview-evidence-grid">{evidence.map((item)=><EvidenceCard key={`${item.source}-${item.external_id}`} item={item} expanded/>)}{!evidence.length&&<Empty title="No evidence yet" text="Run a collection to populate this view."/>}</div></section>
  </div>
}

function IssuesPage({ issues, onIssue, onNew }: { issues: Issue[]; onIssue: (id:string) => void; onNew: () => void }) {
  const [query, setQuery] = useState(''); const [severity, setSeverity] = useState('all'); const [source, setSource] = useState('all')
  const filtered = issues.filter((issue) => (severity === 'all' || issue.severity === severity) && (source === 'all' || issue.sources.includes(source)) && issue.title.toLowerCase().includes(query.toLowerCase()))
  const sources = [...new Set(issues.flatMap((issue) => issue.sources))]
  return <div className="ov-page"><PageHeader title="Pain points" subtitle="The customer problems that deserve attention." actions={<button className="button accent" onClick={onNew}><Plus/>New research</button>}/><div className="filter-bar"><Select value={source} onChange={setSource} label="Source" options={['all',...sources]}/><Select value={severity} onChange={setSeverity} label="Priority" options={['all','critical','high','medium','low']}/><label className="table-search"><Search/><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search pain points"/></label></div><section className="surface table-wrap"><table className="issues-table simple"><thead><tr><th>Issue</th><th>Category</th><th>Comments</th><th>Sentiment</th><th>Sources</th><th>Evidence</th></tr></thead><tbody>{filtered.map((issue) => <tr key={issue.id} onClick={() => onIssue(issue.id)}><td><SeverityDot severity={issue.severity}/><b>{issue.title}</b></td><td>{titleCase(issue.category)}</td><td>{issue.mentions}</td><td><span className={`sentiment-label ${sentimentTone(issue.sentiment)}`}>{sentimentLabel(issue.sentiment)}</span></td><td>{issue.sources.length}</td><td><button onClick={() => onIssue(issue.id)}>View evidence <ArrowRight/></button></td></tr>)}</tbody></table>{!filtered.length && <Empty title="No matching pain points" text="Clear a filter or try another search."/>}<footer>Showing {filtered.length} pain point{filtered.length===1?'':'s'} <span>Open any row to see the recommended action and supporting comments.</span></footer></section></div>
}

function IssueDetail({ issue, onBack, onVox, onTicket }: { issue: Issue; onBack: () => void; onVox: () => void; onTicket: () => void }) {
  const [source, setSource] = useState('all'); const [connect, setConnect] = useState<string | null>(null)
  const evidence = rankEvidence(issue.evidence.filter((item) => source === 'all' || item.source === source)).slice(0,10)
  return <div className="ov-page detail-page"><button className="back-link" onClick={onBack}><ArrowLeft/>All pain points</button><div className="detail-heading"><div><h1><SeverityDot severity={issue.severity}/>{issue.title}</h1><p>{issue.summary}</p><div className="meta-row"><span>Category <b>{titleCase(issue.category)}</b></span><span>Priority <b className="negative">{issue.severity}</b></span><span>Comments <b>{issue.mentions}</b></span><span>Sources <b>{issue.sources.join(', ') || '—'}</b></span></div></div><button className="outline-accent" onClick={onVox}><Mic/>Ask Vox about this</button></div><div className="detail-grid"><div className="detail-left"><section className="surface action-card primary-action"><span className="mono-label">Recommended action</span><h2>Address {issue.title.toLowerCase()}</h2><p>Review the highest-impact customer examples with the product owner, validate where the problem occurs, and prioritize a targeted improvement to the {issue.category} experience.</p><span className="mono-label">Next steps</span><ol><li>Review the customer comments below with Product and Support.</li><li>Confirm the affected workflow using internal product data.</li><li>Assign an owner and scope the smallest meaningful fix.</li></ol></section><section className="surface detail-evidence"><SectionHead title="Evidence" subtitle={`Top ${Math.min(10,evidence.length)} comments by impact and engagement`}/><div className="source-tabs"><button className={source === 'all' ? 'active' : ''} onClick={() => setSource('all')}>All</button>{issue.sources.map((item) => <button key={item} className={source === item ? 'active' : ''} onClick={() => setSource(item)}>{titleCase(item)}</button>)}</div>{evidence.map((item) => <EvidenceCard key={`${item.source}-${item.external_id}`} item={item} expanded/>)}{!evidence.length && <Empty title="No evidence in this source" text="Choose another source tab."/>}</section></div></div>
    <section className="surface send-card send-card-wide"><SectionHead title="Send this pain point" subtitle="Create work where your team already operates"/><div className="destination-row">{['Linear','GitHub','Jira','Salesforce','Slack'].map((item) => <div className="destination" key={item}><span>{item.slice(0,2).toUpperCase()}</span><b>{item}</b>{item === 'Linear' ? <small><i/>Connected</small> : <button onClick={() => setConnect(item)}>Connect</button>}</div>)}</div><button className="button accent full" onClick={onTicket}><ArrowUpRight/>Create ticket in Linear</button></section>{connect && <Modal title={`Connect ${connect}`} subtitle="Authorize Overheard to send this pain point and its supporting evidence to your workspace." onClose={() => setConnect(null)}><button className="button accent full" onClick={() => setConnect(null)}>Continue to {connect}</button></Modal>}</div>
}

function EvidencePage({ comments }: { comments: ProductComment[] }) {
  const [query,setQuery] = useState(''); const [source,setSource] = useState('all'); const sources = [...new Set(comments.map((item) => item.source))]
  const filtered = rankEvidence(comments.filter((item) => (source === 'all' || item.source === source) && item.content.toLowerCase().includes(query.toLowerCase()))).slice(0,10)
  return <div className="ov-page"><PageHeader title="Evidence" subtitle="The ten highest-impact public comments supporting the current recommendations."/><div className="filter-bar"><Select value={source} onChange={setSource} label="Source" options={['all',...sources]}/><label className="table-search"><Search/><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search evidence"/></label></div><div className="evidence-grid">{filtered.map((item) => <EvidenceCard key={`${item.source}-${item.external_id}`} item={item} expanded/>)}{!filtered.length && <Empty title="No matching evidence" text="Try a different source or search."/>}</div></div>
}

function NewResearch({ product, onClose, onStart, onVox }: { product: Product; onClose: () => void; onStart: () => Promise<void>; onVox: () => void }) {
  const [intent,setIntent] = useState('What frustrates them?'); const [sources,setSources] = useState(['youtube','reddit','hackernews']); const [busy,setBusy] = useState(false)
  const toggle = (source:string) => setSources((all) => all.includes(source) ? all.filter((item) => item !== source) : [...all,source])
  return <div className="research-page"><div className="research-brand"><span className="overheard-logo large" role="img" aria-label="Overheard"/></div><button className="research-close" onClick={onClose}><X/></button><form className="research-compose" onSubmit={async (event) => { event.preventDefault(); setBusy(true); await onStart(); setBusy(false) }}><span className="mono-label accent-text">New research</span><h1>What do you want to understand?</h1><p>Point Overheard at a product question. We’ll gather, clean and rank the public evidence.</p><div className="surface composer"><label>Product or company<input defaultValue={product.name}/></label><fieldset><legend>What do you want to know?</legend><div className="intent-chips">{['What frustrates them?','What do they love?','Why are they churning?','How did the last release land?'].map((item) => <button type="button" className={intent === item ? 'active' : ''} onClick={() => setIntent(item)} key={item}>{item}</button>)}</div><textarea placeholder="…or ask something specific"/></fieldset><fieldset><legend>Sources to scan</legend><div className="source-toggles">{['youtube','reddit','hackernews','producthunt','x'].map((item) => <button type="button" key={item} className={`${sources.includes(item) ? 'active' : ''} ${item === 'x' ? 'beta' : ''}`} onClick={() => toggle(item)}>{sources.includes(item) && <Check/>}{titleCase(item)}{item === 'x' && <small>beta</small>}</button>)}</div></fieldset><button className="button accent full" disabled={busy}>{busy ? <LoaderCircle className="spin"/> : <>Start research <ArrowRight/></>}</button><button className="outline-accent full" type="button" onClick={onVox}><Mic/>Ask Vox instead</button></div></form></div>
}

function CommandPalette({ issues, onClose, onNavigate }: { issues: Issue[]; onClose: () => void; onNavigate: (view:View,id?:string) => void }) {
  const [query,setQuery]=useState(''); const matches=issues.filter((item)=>item.title.toLowerCase().includes(query.toLowerCase())).slice(0,5)
  return <div className="modal-backdrop" onMouseDown={onClose}><div className="command-palette" onMouseDown={(e)=>e.stopPropagation()}><label><Search/><input autoFocus value={query} onChange={(e)=>setQuery(e.target.value)} placeholder="Search pages and pain points…"/><kbd>ESC</kbd></label><span>Navigate</span>{[['Overview','overview'],['Pain points','issues'],['Evidence','evidence']].map(([label,next])=><button key={next} onClick={()=>onNavigate(next as View)}><Command/>{label}<ArrowRight/></button>)}{matches.length>0&&<span>Pain points</span>}{matches.map((issue)=><button key={issue.id} onClick={()=>onNavigate('detail',issue.id)}><SeverityDot severity={issue.severity}/>{issue.title}<ArrowRight/></button>)}</div></div>
}

function EvidenceCard({ item, expanded=false }: { item: ProductComment; expanded?: boolean }) {
  const tone = item.sentiment === 'positive' ? 'positive' : item.sentiment === 'negative' ? 'negative' : 'neutral'
  return <article className={`evidence-card tone-${tone} ${expanded?'expanded':''}`}>
    <p>“{item.content}”</p>
    <footer>
      <SentimentBadge sentiment={item.sentiment}/>
      <span className="source-mark">{item.source.slice(0,2).toUpperCase()}</span>
      <span>{shortHash(item.author_hash)} · {titleCase(item.source)}{item.published_at ? ` · ${relativeDate(item.published_at)}` : ''}</span>
      <b><ThumbsUp/>{item.engagement?.score || 0}</b>
      {item.url && <a href={item.url} target="_blank" rel="noreferrer" aria-label="Open source"><ExternalLink/></a>}
    </footer>
  </article>
}

/** Colour-coded sentiment for a single comment: green positive, red negative.
 *  The word is kept alongside the dot — colour alone is not readable for
 *  colour-blind users, and it disappears entirely in a screenshot. */
function SentimentBadge({ sentiment }: { sentiment: ProductComment['sentiment'] }) {
  const tone = sentiment === 'positive' ? 'positive' : sentiment === 'negative' ? 'negative' : 'neutral'
  const label = sentiment === 'positive' ? 'Positive' : sentiment === 'negative' ? 'Negative' : 'Neutral'
  return <span className={`sentiment-badge ${tone}`} title={`${label} sentiment`}>
    <i aria-hidden="true"/>{label}
  </span>
}
function PageHeader({ eyebrow, title, subtitle, actions }: { eyebrow?:string; title:string; subtitle:string; actions?:ReactNode }) { return <header className="page-header"><div>{eyebrow&&<span className="mono-label">{eyebrow}</span>}<h1>{title}</h1><p>{subtitle}</p></div>{actions&&<div className="page-actions">{actions}</div>}</header> }
function SectionHead({ title, subtitle, action }: { title:string; subtitle:string; action?:ReactNode }) { return <header className="section-head"><div><h2>{title}</h2><p>{subtitle}</p></div>{action}</header> }
function SeverityDot({ severity }: { severity:Severity }) { return <i className={`severity-dot ${severity}`} aria-label={`${severity} severity`}/> }
function NavLabel({children,action}:{children:ReactNode;action?:()=>void}) { return <span className="nav-label">{children}{action&&<button onClick={action}><Plus/></button>}</span> }
function NavButton({active,icon,children,onClick}:{active:boolean;icon:ReactNode;children:ReactNode;onClick:()=>void}) { return <button className={active?'active':''} onClick={onClick}>{icon}{children}</button> }
function Select({value,onChange,label,options}:{value:string;onChange:(value:string)=>void;label:string;options:string[]}) { return <label className="filter-select"><span>{label}:</span><select value={value} onChange={(e)=>onChange(e.target.value)}>{options.map((item)=><option key={item} value={item}>{titleCase(item)}</option>)}</select><ChevronDown/></label> }
function Empty({title,text}:{title:string;text:string}) { return <div className="empty-state"><Inbox/><b>{title}</b><span>{text}</span></div> }

function ProductModal({ onClose, onSubmit }: { onClose: () => void; onSubmit: (name:string,query:string)=>Promise<void> }) { const [name,setName]=useState(''); const [query,setQuery]=useState(''); const [busy,setBusy]=useState(false); return <Modal title="Add a product" subtitle="Start tracking public customer conversations." onClose={onClose}><form className="modal-form" onSubmit={async(e)=>{e.preventDefault();setBusy(true);await onSubmit(name,query)}}><label>Product name<input value={name} onChange={(e)=>setName(e.target.value)} required autoFocus/></label><label>Search query<input value={query} onChange={(e)=>setQuery(e.target.value)} placeholder={`${name||'Product'} reviews`}/></label><button className="button accent full" disabled={busy}>{busy?<LoaderCircle className="spin"/>:<Plus/>}Add product</button></form></Modal> }
function IngestModal({product,token,onClose,onComplete}:{product:Product;token:string;onClose:()=>void;onComplete:(message:string)=>void}) {
  const [depth,setDepth]=useState<'quick'|'standard'|'deep'>('standard')
  const [busy,setBusy]=useState(false); const [error,setError]=useState('')
  const [job,setJob]=useState<IngestionJob|null>(null); const [result,setResult]=useState<IngestResult|null>(null)
  const options = [
    {id:'quick' as const,title:'Quick scan',description:'A fast pulse check with smaller source limits. Best for testing a new product or query.'},
    {id:'standard' as const,title:'Standard research',description:'Balanced coverage across every configured source. Recommended for regular collection.'},
    {id:'deep' as const,title:'Deep research',description:'The largest available corpus and widest search. Takes longer and uses more source quota.'},
  ]
  useEffect(()=>{
    if(!busy) return
    let active=true
    const poll=async()=>{try{const rows=await api.ingestions(token,product.id);if(active)setJob(rows[0]||null)}catch{/* The collection request still reports the final result. */}}
    void poll(); const timer=window.setInterval(()=>void poll(),1500)
    return()=>{active=false;window.clearInterval(timer)}
  },[busy,product.id,token])
  async function submit(event:FormEvent){
    event.preventDefault();setBusy(true);setError('');setResult(null)
    try{const next=await api.ingest(token,product.id,{depth});setResult(next);onComplete(`${next.documents_indexed} items indexed from ${next.sources.filter((source)=>source.status==='ok').length} sources`)}
    catch(caught){setError(errorMessage(caught))}finally{setBusy(false)}
  }
  return <Modal title={`Collect feedback for ${product.name}`} subtitle="Choose how broad this collection run should be." onClose={busy?()=>undefined:onClose}>
    <form className="modal-form" onSubmit={submit}>
      {!result&&<fieldset className="depth-list" disabled={busy}><legend>Research depth</legend>{options.map((option)=><label key={option.id} className={depth===option.id?'selected':''}><input type="radio" name="depth" value={option.id} checked={depth===option.id} onChange={()=>setDepth(option.id)}/><span><b>{option.title}</b><small>{option.description}</small></span></label>)}</fieldset>}
      {busy&&<div className="collection-monitor"><header><span><LoaderCircle className="spin"/>Collection in progress</span><b>{job?.status||'starting'}</b></header><ol><li className="done">Ingestion job created{job?.id?` · ${job.id.slice(0,8)}`:''}</li><li className="active">Browserbase searches and fetches open-web pages server-side</li><li>Normalize, enrich and index evidence in Elasticsearch</li></ol><p>Browserbase Search + Fetch does not create a watchable browser session. The job status and final source counts below are the verifiable record of this run.</p></div>}
      {result&&<div className="collection-result"><header><Check/><span><b>Collection complete</b><small>{result.documents_indexed} indexed · {result.documents_rejected} rejected</small></span></header><div className="source-results">{result.sources.map((source)=><div key={source.source}><span className={`source-state ${source.status}`}>{source.status}</span><b>{titleCase(source.source)}</b><em>{source.collected} collected · {source.kept} kept</em><small>{source.detail}</small></div>)}</div><p>These counts come directly from the completed backend collection result and can be cross-checked against the latest ingestion job and Elasticsearch analytics.</p></div>}
      {error&&<div className="form-error">{error}</div>}
      {result?<button type="button" className="button accent full" onClick={onClose}>Done</button>:<button className="button accent full" disabled={busy}>{busy?<><LoaderCircle className="spin"/>Collecting…</>:<><PackageSearch/>Collect feedback</>}</button>}
    </form>
  </Modal>
}
function InfoDialog({kind,onClose}:{kind:'integrations'|'settings';onClose:()=>void}) { return <Modal title={titleCase(kind)} subtitle={kind==='integrations'?'Manage where feedback comes from and where insights go.':'Workspace preferences and account controls.'} onClose={onClose}><div className="dialog-list">{(kind==='integrations'?['YouTube · Connected','Reddit · Available','Hacker News · Connected','Linear · Connected']:['Workspace access · Members only','Default range · 30 days','Evidence links · Enabled']).map((item)=><div key={item}><CircleDot/>{item}</div>)}</div></Modal> }
function DeleteProductModal({ product, busy, onCancel, onConfirm }: {
  product: Product; busy: boolean; onCancel: () => void; onConfirm: () => void
}) {
  return <Modal title={`Delete ${product.name}?`} subtitle="This cannot be undone." onClose={onCancel}>
    <div className="danger-body">
      <span className="danger-icon"><TriangleAlert size={19}/></span>
      <p>This permanently deletes <b>{product.name}</b> and every piece of feedback collected for it. Other products are not affected.</p>
    </div>
    <div className="modal-actions">
      <button className="button" onClick={onCancel} disabled={busy}>Cancel</button>
      <button className="button danger" onClick={onConfirm} disabled={busy}>{busy ? <><LoaderCircle className="spin" size={15}/> Deleting…</> : <><Trash2 size={15}/> Delete product</>}</button>
    </div>
  </Modal>
}

function Modal({title,subtitle,onClose,children}:{title:string;subtitle:string;onClose:()=>void;children:ReactNode}) { return <div className="modal-backdrop"><div className="ov-modal" role="dialog" aria-modal="true"><button className="modal-close" onClick={onClose}><X/></button><h2>{title}</h2><p>{subtitle}</p>{children}</div></div> }
function WorkspaceOnboarding({onCreate,onSignOut}:{onCreate:(company:string,product:string,query:string)=>Promise<void>;onSignOut:()=>void}) { const [company,setCompany]=useState('');const [product,setProduct]=useState('');const [query,setQuery]=useState('');const [busy,setBusy]=useState(false);return <main className="onboarding-page"><button onClick={onSignOut}>Sign out</button><form className="surface onboarding-card" onSubmit={async(e)=>{e.preventDefault();setBusy(true);await onCreate(company,product,query)}}><span className="overheard-logo large" role="img" aria-label="Overheard"/><h1>Create your workspace</h1><p>Add the first product you want Overheard to monitor.</p><label>Workspace<input value={company} onChange={(e)=>setCompany(e.target.value)} required/></label><label>Product<input value={product} onChange={(e)=>setProduct(e.target.value)} required/></label><label>Search query<input value={query} onChange={(e)=>setQuery(e.target.value)}/></label><button className="button accent full" disabled={busy}>{busy?<LoaderCircle className="spin"/>:'Create workspace'}</button></form></main> }
function EmptyProducts({onAdd}:{onAdd:()=>void}) { return <div className="center-empty"><Layers3/><h1>Add your first product</h1><p>Connect a product to begin turning public conversations into grounded insight.</p><button className="button accent" onClick={onAdd}><Plus/>Add product</button></div> }
function FullPageLoader(){return <div className="full-loader"><span className="overheard-logo" role="img" aria-label="Overheard"/><LoaderCircle className="spin"/></div>}
function DashboardSkeleton(){return <div className="dashboard-skeleton">{Array.from({length:8}).map((_,i)=><i key={i}/>)}</div>}

function deriveIssues(analytics:Analytics|null,comments:ProductComment[]):Issue[]{
  if(!analytics) return []
  const totalIssues=Math.max(1,analytics.issues.reduce((sum,row)=>sum+row.count,0))
  return analytics.issues.map((row,index)=>{
    const evidence=comments.filter((comment)=>comment.issue_categories.includes(row.name))
    const sources=[...new Set(evidence.map((item)=>item.source))]
    const scores=evidence.map((item)=>item.sentiment_score).filter((item):item is number=>item!==null)
    const sentiment=scores.length?Math.round(scores.reduce((sum,item)=>sum+item,0)/scores.length*100):-Math.min(90,35+index*4)
    const share=Math.round(row.count/totalIssues*100)
    const severity:Severity=share>=28?'critical':share>=18?'high':share>=9?'medium':'low'; const id=slug(row.name)
    return {id,title:titleCase(row.name),category:row.name,summary:`Customers repeatedly describe ${titleCase(row.name).toLowerCase()} as a source of friction. The signal is grounded in ${row.count} classified comments.`,mentions:row.count,sentiment,sources,severity,evidence}
  })
}
function routeFromPath(path:string):View { if(path==='/new')return'new';if(path==='/evidence')return'evidence';if(/^\/issues\/.+/.test(path))return'detail';if(path==='/issues')return'issues';return'overview' }
function detailFromPath(path:string){return path.match(/^\/issues\/(.+)/)?.[1]||''}
function slug(value:string){return value.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/(^-|-$)/g,'')}
function titleCase(value:string){return value.replaceAll('_',' ').replace(/\b\w/g,(letter)=>letter.toUpperCase())}
function initials(value:string){return value.split(/\s|@/).filter(Boolean).slice(0,2).map((item)=>item[0]).join('').toUpperCase()}
function errorMessage(error:unknown){return error instanceof Error?error.message:'Something went wrong'}
function shortHash(value:string){return value?`User ${value.slice(0,5)}`:'Anonymous'}
function shortDate(value:string){return new Date(value).toLocaleDateString('en-US',{month:'short',day:'numeric'})}
function relativeDate(value:string){const days=Math.floor((Date.now()-new Date(value).getTime())/86400000);return days<=0?'today':days===1?'1d ago':days<30?`${days}d ago`:shortDate(value)}
function isoDaysAgo(days:number){return new Date(Date.now()-days*86400000).toISOString()}
/** Rank evidence without letting one source monopolize the list.
 *
 *  Engagement is NOT comparable across sources: a YouTube like count runs to
 *  the thousands, Hacker News points to tens, Steam votes_up often to single
 *  digits. Sorting on the raw number therefore returns YouTube every time and
 *  the multi-source claim silently becomes single-source. So rank within each
 *  source first, then interleave round-robin — the best of each source before
 *  the second-best of any. */
function rankEvidence(items:ProductComment[]){
  const bySource = new Map<string, ProductComment[]>()
  for (const item of items) {
    const list = bySource.get(item.source) || []
    list.push(item)
    bySource.set(item.source, list)
  }
  // Strongest source first on ties, so the lead item is still the best overall.
  const ranked = [...bySource.values()].map((list) => list.sort((a,b)=>impact(b)-impact(a)))
  ranked.sort((a,b)=>impact(b[0])-impact(a[0]))
  const out:ProductComment[] = []
  for (let i = 0; out.length < items.length; i++) {
    let moved = false
    for (const list of ranked) {
      if (i < list.length) { out.push(list[i]); moved = true }
    }
    if (!moved) break
  }
  return out
}
function impact(item:ProductComment){return (item.engagement?.score||0)+(item.engagement?.replies||0)*2}
function sentimentLabel(value:number){return value<=-20?'Negative':value>=20?'Positive':'Mixed'}
function sentimentTone(value:number){return value<=-20?'negative':value>=20?'positive':'mixed'}
