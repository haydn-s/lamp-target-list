import { useEffect, useState } from 'react'
import './App.css'

type Health = { status: 'ok'; schema_version: number }

type ApiState =
  | { kind: 'loading' }
  | { kind: 'ok'; health: Health }
  | { kind: 'error'; message: string }

function App() {
  const [api, setApi] = useState<ApiState>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/health', { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        setApi({ kind: 'ok', health: (await res.json()) as Health })
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setApi({ kind: 'error', message: err instanceof Error ? err.message : String(err) })
      })
    return () => controller.abort()
  }, [])

  return (
    <div className="app">
      <header className="app-header">
        <h1>LAMP Target List</h1>
        <ApiStatus state={api} />
      </header>
      <main className="app-main">
        <p>The board, dashboard and contacts views arrive in Phase 1.</p>
      </main>
    </div>
  )
}

function ApiStatus({ state }: { state: ApiState }) {
  switch (state.kind) {
    case 'loading':
      return <span className="api-status">Connecting to API…</span>
    case 'ok':
      return (
        <span className="api-status ok">
          API connected · schema v{state.health.schema_version}
        </span>
      )
    case 'error':
      return (
        <span className="api-status error" role="alert">
          API unreachable: {state.message}
        </span>
      )
  }
}

export default App
