import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const outputDirectory = new URL('../../.qa/', import.meta.url)
await mkdir(outputDirectory, { recursive: true })

const browser = await chromium.launch({ headless: true })
const errors = []
try {
  const desktop = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
  desktop.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  desktop.on('pageerror', (error) => errors.push(error.message))
  await desktop.goto('http://127.0.0.1:3000', { waitUntil: 'networkidle' })
  await desktop.getByRole('heading', { name: 'Sign in to your workspace' }).waitFor()
  await desktop.locator('.auth-card').evaluate((element) => element.getAnimations().map((animation) => animation.finish()))
  await desktop.screenshot({ path: fileURLToPath(new URL('auth-desktop.png', outputDirectory)), fullPage: true })

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 })
  await mobile.goto('http://127.0.0.1:3000', { waitUntil: 'networkidle' })
  await mobile.getByRole('heading', { name: 'Sign in to your workspace' }).waitFor()
  await mobile.locator('.auth-card').evaluate((element) => element.getAnimations().map((animation) => animation.finish()))
  await mobile.screenshot({ path: fileURLToPath(new URL('auth-mobile.png', outputDirectory)), fullPage: true })

  const dashboardContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const now = Math.floor(Date.now() / 1000)
  const session = {
    access_token: 'visual-test-token', refresh_token: 'visual-test-refresh',
    expires_in: 3600, expires_at: now + 3600, token_type: 'bearer',
    user: {
      id: '11111111-1111-4111-8111-111111111111', aud: 'authenticated', role: 'authenticated',
      email: 'alex@acme.com', app_metadata: { provider: 'email', providers: ['email'] },
      user_metadata: { full_name: 'Alex Morgan' }, identities: [],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(), is_anonymous: false,
    },
  }
  await dashboardContext.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
    key: 'sb-qvasljzqbhzmufzfjdus-auth-token', value: session,
  })
  const dashboard = await dashboardContext.newPage()
  dashboard.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  dashboard.on('pageerror', (error) => errors.push(error.message))
  await dashboard.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const organization = { id: '22222222-2222-4222-8222-222222222222', name: 'Northstar Labs', created_by: session.user.id, created_at: new Date().toISOString() }
    const product = { id: '33333333-3333-4333-8333-333333333333', organization_id: organization.id, name: 'iPhone 18', youtube_query: 'iPhone 18 review', active: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
    let body
    if (path === '/api/config/public') body = { supabase_url: 'https://qvasljzqbhzmufzfjdus.supabase.co', supabase_publishable_key: 'visual-test-key' }
    else if (path === '/api/organizations') body = [organization]
    else if (path.includes('/organizations/') && path.endsWith('/products')) body = [product]
    else if (path.endsWith('/analytics')) body = {
      product: product.name, total_comments: 477, complaint_count: 60, complaint_rate: .1258,
      average_sentiment: .2744, average_likes: 2.7,
      sentiment: [{ name: 'positive', count: 271 }, { name: 'neutral', count: 143 }, { name: 'negative', count: 63 }],
      issues: [{ name: 'audio_video', count: 64 }, { name: 'performance', count: 39 }, { name: 'pricing', count: 26 }, { name: 'reliability', count: 18 }, { name: 'usability', count: 14 }],
      timeline: ['2026-03','2026-04','2026-05','2026-06','2026-07','2026-08','2026-09'].map((month, index) => ({ month: `${month}-01T00:00:00Z`, count: [31,48,43,67,71,92,125][index] })),
      videos: Array.from({ length: 5 }, (_, index) => ({ video_id: `video-${index}`, title: ['iPhone 18: Everything you need to know','My honest iPhone 18 review after one week','The biggest iPhone upgrade in years?','iPhone 18 camera test and comparison','Before you buy the iPhone 18'][index], comment_count: [92,81,73,58,49][index], average_sentiment: [.22,.36,.18,.42,.09][index] })),
    }
    else if (path.endsWith('/comments')) body = [
      { id: 'c1', author: 'Maya R.', text: 'The camera is incredible, but battery drain during video recording is still a real problem.', video_id: 'v1', video_title: 'My honest iPhone 18 review after one week', like_count: 84, published_at: new Date(Date.now()-86400000).toISOString(), sentiment: 'negative', sentiment_score: -.42, is_complaint: true, issue_categories: ['audio_video','performance'] },
      { id: 'c2', author: 'Jordan Lee', text: 'Face ID finally feels instant. This is the kind of quality-of-life improvement I wanted.', video_id: 'v2', video_title: 'iPhone 18: Everything you need to know', like_count: 51, published_at: new Date(Date.now()-172800000).toISOString(), sentiment: 'positive', sentiment_score: .78, is_complaint: false, issue_categories: ['usability'] },
      { id: 'c3', author: 'Sam K.', text: 'Great phone, but the price jump is difficult to justify for such a small storage tier.', video_id: 'v3', video_title: 'Before you buy the iPhone 18', like_count: 39, published_at: new Date(Date.now()-259200000).toISOString(), sentiment: 'neutral', sentiment_score: -.08, is_complaint: true, issue_categories: ['pricing'] },
    ]
    else body = {}
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await dashboard.goto('http://127.0.0.1:3000', { waitUntil: 'networkidle' })
  await dashboard.getByRole('heading', { name: 'iPhone 18' }).waitFor()
  await dashboard.locator('.dashboard-content').evaluate((element) => element.getAnimations({ subtree: true }).map((animation) => animation.finish()))
  await dashboard.screenshot({ path: fileURLToPath(new URL('dashboard-desktop.png', outputDirectory)), fullPage: true })
  await dashboard.setViewportSize({ width: 390, height: 844 })
  await dashboard.locator('body').evaluate((element) => element.getAnimations({ subtree: true }).map((animation) => animation.finish()))
  await dashboard.screenshot({ path: fileURLToPath(new URL('dashboard-mobile.png', outputDirectory)), fullPage: true })
  await dashboardContext.close()

  if (errors.length) throw new Error(`Browser errors:\n${errors.join('\n')}`)
  console.log('Visual check passed: auth and analytical dashboard rendered without browser errors.')
} finally {
  await browser.close()
}
