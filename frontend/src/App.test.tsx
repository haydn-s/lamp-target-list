import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App.tsx'

function stubFetch(result: () => Promise<unknown>) {
  vi.stubGlobal('fetch', vi.fn(result))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('shows the schema version once the API answers', async () => {
    stubFetch(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ status: 'ok', schema_version: 1 }),
    }))
    render(<App />)
    expect(await screen.findByText(/schema v1/)).toBeInTheDocument()
  })

  it('says so when the API is unreachable', async () => {
    stubFetch(() => Promise.reject(new TypeError('Failed to fetch')))
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to fetch')
  })

  it('treats an HTTP error as unreachable', async () => {
    stubFetch(async () => ({ ok: false, status: 502, json: async () => ({}) }))
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 502')
  })
})
