import type { SizeResult } from './types'

// Zero sizing logic here — pure transport to the API.

const cfg = {
  get baseUrl() { return localStorage.getItem('sizer.baseUrl') || '' },
  get apiKey() { return localStorage.getItem('sizer.apiKey') || 'sizer-dev-key' },
}

export function setApiConfig(baseUrl: string, apiKey: string) {
  localStorage.setItem('sizer.baseUrl', baseUrl)
  localStorage.setItem('sizer.apiKey', apiKey)
}

async function call(path: string, init?: RequestInit): Promise<Response> {
  return fetch(cfg.baseUrl + path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': cfg.apiKey,
      'X-Interface': 'ui',
      ...(init?.headers || {}),
    },
  })
}

export async function sizeTrade(request: Record<string, unknown>, accountMode: boolean): Promise<SizeResult> {
  const body = accountMode ? { mode: 'account', request } : request
  const r = await call('/v1/size', { method: 'POST', body: JSON.stringify(body) })
  const json = await r.json()
  if (r.status === 200) return { kind: 'ok', body: json }
  if (r.status === 422) return { kind: 'refusal', body: json }
  return { kind: 'error', body: json.detail ? { error: String(json.detail) } : json }
}

export async function compareScenarios(requests: Record<string, unknown>[], labels: string[]) {
  const r = await call('/v1/scenarios/compare', {
    method: 'POST',
    body: JSON.stringify({ requests, labels }),
  })
  return r.json()
}

export async function getPortfolio() {
  const r = await call('/v1/portfolio')
  return r.ok ? r.json() : null
}

export async function putAccount(body: Record<string, unknown>) {
  const r = await call('/v1/account', { method: 'PUT', body: JSON.stringify(body) })
  return r.json()
}

export async function addPosition(body: Record<string, unknown>) {
  const r = await call('/v1/portfolio/position', { method: 'POST', body: JSON.stringify(body) })
  return r.json()
}

export async function deletePosition(id: string) {
  await call(`/v1/portfolio/position/${id}`, { method: 'DELETE' })
}

export async function logTrades(strategyId: string, resultsR: number[]) {
  const r = await call('/v1/track-record', {
    method: 'POST',
    body: JSON.stringify({ strategy_id: strategyId, results_r: resultsR }),
  })
  return r.json()
}

export async function getTrackRecord(strategyId: string) {
  const r = await call(`/v1/track-record/${strategyId}`)
  return r.ok ? r.json() : null
}

export async function getInstrument(id: string) {
  const r = await call(`/v1/instruments/${encodeURIComponent(id)}`)
  return r.ok ? r.json() : null
}
