import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ConversationProvider, useConversation } from '@elevenlabs/react'
import { ArrowUpRight, Mic, Send, X } from 'lucide-react'
import { api } from '../lib/api'
import type { Product } from '../types'

type Turn = { role: 'vox' | 'user'; text: string; id: number }
type Voice = { voice_id: string; name: string }
type Recognition = {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null
  onend: (() => void) | null
  onerror: ((event: { error: string }) => void) | null
  start: () => void
  abort: () => void
}
type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognition
  webkitSpeechRecognition?: new () => Recognition
}

export function VoxPanel(props: {
  product: Product
  token: string
  issues: { id: string; title: string }[]
  onClose: () => void
  onOpenIssue: (id: string) => void
}) {
  return <ConversationProvider><VoxSession {...props} /></ConversationProvider>
}

function VoxSession({ product, token, issues, onClose, onOpenIssue }: Parameters<typeof VoxPanel>[0]) {
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [voices, setVoices] = useState<Voice[]>([])
  const [voiceId, setVoiceId] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState('')
  const [input, setInput] = useState('')
  const [liveText, setLiveText] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const nextId = useRef(0)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const recognitionRef = useRef<Recognition | null>(null)
  const pendingRef = useRef('')
  const sendMessageRef = useRef<(text: string) => void>(() => {})
  const startRef = useRef<(voice: string, force: boolean) => void>(() => {})
  const restartVoiceRef = useRef<string | null>(null)

  const conversation = useConversation({
    onConnect: () => {
      setConnecting(false)
      if (pendingRef.current) {
        sendMessageRef.current(pendingRef.current)
        pendingRef.current = ''
      }
    },
    onMessage: (message) => {
      const text = message.message?.trim()
      if (!text) return
      if (message.source === 'user') {
        setLiveText('')
        try { recognitionRef.current?.abort() } catch { /* recognition has stopped */ }
      }
      setTurns((items) => [...items, {
        role: message.source === 'user' ? 'user' : 'vox', text, id: nextId.current++,
      }])
    },
    onError: (reason) => {
      setError(String(reason))
      setConnecting(false)
    },
    onDisconnect: (details) => {
      setConnecting(false)
      setLiveText('')
      if (details.reason === 'error') setError(details.message || 'Voice connection failed')
      if (restartVoiceRef.current) {
        const nextVoice = restartVoiceRef.current
        restartVoiceRef.current = null
        window.setTimeout(() => startRef.current(nextVoice, true), 0)
      }
    },
  })
  const connected = conversation.status === 'connected'
  const speaking = connected && conversation.isSpeaking
  const endRef = useRef(conversation.endSession)

  useEffect(() => {
    api.voiceConfig().then((result) => setConfigured(result.configured)).catch(() => setConfigured(false))
    api.voices(token).then((result) => {
      setVoices(result.voices)
      setVoiceId(result.voices[0]?.voice_id || '')
    }).catch(() => {})
  }, [token])

  useEffect(() => () => { restartVoiceRef.current = null; void endRef.current() }, [])

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, liveText])

  const setMuted = conversation.setMuted
  useEffect(() => {
    if (connected) setMuted(speaking)
  }, [connected, speaking, setMuted])

  // Browser speech recognition supplies interim text; ElevenLabs supplies the
  // authoritative final transcript and audio. Browsers without this API still
  // get the final transcript.
  useEffect(() => {
    if (!connected || speaking) return
    const speechWindow = window as SpeechWindow
    const Constructor = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition
    if (!Constructor) return
    const recognition = new Constructor()
    let active = true
    let restart: number | undefined
    recognitionRef.current = recognition
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'
    recognition.onresult = (event) => {
      const words = Array.from(event.results, (result) => result[0]?.transcript || '').join(' ').trim()
      setLiveText(words)
    }
    recognition.onerror = (event) => {
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') active = false
    }
    recognition.onend = () => {
      if (active) restart = window.setTimeout(() => {
        try { recognition.start() } catch { active = false }
      }, 150)
    }
    try { recognition.start() } catch { active = false }
    return () => {
      active = false
      clearTimeout(restart)
      recognition.onend = null
      recognition.onresult = null
      recognition.onerror = null
      try { recognition.abort() } catch { /* already stopped */ }
      if (recognitionRef.current === recognition) recognitionRef.current = null
      setLiveText('')
    }
  }, [connected, speaking])

  async function start(selectedVoice = voiceId, force = false) {
    if (!force && (connecting || connected)) return
    setError('')
    setConnecting(true)
    try {
      const session = await api.voiceSignedUrl(token, product.id)
      await conversation.startSession({
        signedUrl: session.signed_url,
        connectionType: 'websocket',
        dynamicVariables: {
          product_name: session.product_name,
          secret__scope_token: session.scope_token,
        },
        overrides: {
          agent: { firstMessage: `Hi, I'm Vox. Ask me what customers are saying about ${session.product_name}.` },
          ...(selectedVoice ? { tts: { voiceId: selectedVoice } } : {}),
        },
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not start voice')
      setConnecting(false)
    }
  }
  useEffect(() => {
    sendMessageRef.current = conversation.sendUserMessage
    endRef.current = conversation.endSession
    startRef.current = (voice, force) => { void start(voice, force) }
  })

  async function changeVoice(nextId: string) {
    setVoiceId(nextId)
    if (connected) {
      restartVoiceRef.current = nextId
      await conversation.endSession()
    }
  }

  function ask(question: string) {
    const value = question.trim()
    if (!value) return
    setInput('')
    if (connected) conversation.sendUserMessage(value)
    else {
      pendingRef.current = value
      if (!connecting) void start()
    }
  }

  function close() {
    void conversation.endSession()
    onClose()
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    ask(input)
  }

  return <aside className="vox-panel" aria-label="Ask Vox">
    <header><div><b>Vox</b><span>market-research analyst · {product.name}</span></div>
      {connected && <span className={`listening ${speaking ? 'talking' : ''}`}><i/>{speaking ? 'Talking' : 'Listening'}</span>}
      <button aria-label="Close Ask Vox" onClick={close}><X/></button>
    </header>
    <button className={`mic-orb ${connected ? 'active' : ''} ${speaking ? 'speaking' : ''}`} type="button"
      aria-label={connected ? 'End voice conversation' : 'Start voice conversation'}
      disabled={connecting || configured === false} onClick={() => connected ? void conversation.endSession() : void start()}><Mic/></button>
    <p className="vox-voice-action">{connecting ? 'Connecting…' : connected ? 'Tap the microphone to end' : 'Tap the microphone to talk'}</p>
    {error && <p className="vox-error" role="alert">{error}</p>}
    {configured === false && <p className="vox-error" role="alert">ElevenLabs is not configured.</p>}
    <div className="transcript" ref={transcriptRef} aria-live="polite">
      {!turns.length && <div className="vox">Ask about the feedback collected for {product.name}.</div>}
      {turns.map((turn) => <div key={turn.id} className={turn.role}>{turn.text}</div>)}
      {liveText && <div className="user interim">{liveText}…</div>}
    </div>
    <div className="suggestions">{['Brief me on feedback', 'Compare sources', 'Top 3 to fix'].map((question) =>
      <button key={question} type="button" disabled={configured === false} onClick={() => ask(question)}>{question}</button>)}</div>
    {issues[0] && <button className="vox-link" onClick={() => onOpenIssue(issues[0].id)}>Open top pain point <ArrowUpRight/></button>}
    <form className="challenge" onSubmit={submit}><label>Ask a question<input value={input}
      onChange={(event) => { setInput(event.target.value); if (connected) conversation.sendUserActivity() }}
      disabled={configured === false} placeholder="Ask for the evidence…"/></label>
      <button aria-label="Send question" disabled={!input.trim() || configured === false}><Send/></button></form>
    <footer><select aria-label="Voice" value={voiceId} disabled={!voices.length} onChange={(event) => void changeVoice(event.target.value)}>
      {!voices.length && <option value="">Voices unavailable</option>}{voices.map((voice) => <option key={voice.voice_id} value={voice.voice_id}>{voice.name}</option>)}
    </select><button onClick={close}>End</button></footer>
  </aside>
}
