// The panel's API, served by `puxirum panel` (src/puxirum/panel.py). Read-only.
import { onScopeDispose, ref, shallowRef, watch, type Ref } from 'vue'

export interface ProjectRef {
  id: string
  name: string
  branch: string | null
}

export interface LineNode {
  id: string
  name: string
  kind: 'agent' | 'core'
  files: string
  stages: string[]
}

export interface Loop {
  id: string
  from: string
  to: string
  label: string
  count: number
}

export interface Round {
  n: number
  gate: string | null
  reviews: Record<string, string | null>
}

export interface RunningAgent {
  role: string
  lens: string | null
  round: number
  attempt: number
  doing: string | null
}

export interface Job {
  id: string
  issue: number
  title: string
  stage: string
  node: string
  active: boolean
  waiting: 'author' | 'you' | null
  reason: string | null
  round: number
  round_limit: number
  risk: string | null
  surfaces: string[]
  reviewers: Record<string, string>
  pr: number | null
  pr_url: string | null
  cost_usd: number
  active_seconds: number
  waiting_seconds: number
  by_role: Record<string, number>
  loops: { gate: number; review: number; feedback: number; questions: number }
  rounds: Round[]
  running: RunningAgent[]
  timeline: { at: string; from: string; to: string }[]
  files: { path: string; bytes: number }[]
  created: string
  stage_started: string
  ended: string | null
}

export interface State {
  project: { id: string; name: string; branch: string | null; label: string | null }
  problem: string | null
  line: LineNode[]
  loops: Loop[]
  jobs: Job[]
  totals: {
    active: number
    waiting: number
    merged: number
    rejected: number
    cost_usd: number
    coordination_usd: number
  }
}

export interface FeedStep {
  at: string
  who: string
  text: string
}

export async function fetchProjects(): Promise<ProjectRef[]> {
  const res = await fetch('/api/projects')
  if (!res.ok) throw new Error(`projects: ${res.status}`)
  return res.json()
}

export async function fetchJobFile(project: string, job: string, path: string): Promise<string> {
  const res = await fetch(`/api/projects/${encodeURIComponent(project)}/jobs/${encodeURIComponent(job)}/files/${path}`)
  if (!res.ok) throw new Error(`${path}: ${res.status}`)
  return res.text()
}

const FEED_KEEP = 200

/** The project's state, kept current by the server's events, and the live steps of its agents. */
export function useProjectLive(project: Ref<string | undefined>) {
  const state = shallowRef<State | null>(null)
  const feed = ref<FeedStep[]>([])
  const connected = ref(false)
  let source: EventSource | null = null

  function close() {
    source?.close()
    source = null
    connected.value = false
  }

  watch(
    project,
    (id) => {
      close()
      state.value = null
      feed.value = []
      if (!id) return
      // The first picture comes from a plain request; the stream keeps it current.
      fetch(`/api/projects/${encodeURIComponent(id)}/state`)
        .then((res) => (res.ok ? res.json() : null))
        .then((s: State | null) => {
          if (s && project.value === id && state.value === null) state.value = s
        })
        .catch(() => {})
      source = new EventSource(`/api/projects/${encodeURIComponent(id)}/events`)
      source.onopen = () => (connected.value = true)
      source.onerror = () => (connected.value = false) // EventSource reconnects by itself
      source.addEventListener('state', (e) => {
        state.value = JSON.parse((e as MessageEvent).data)
      })
      // The latest steps so far, sent on every (re)connection: they replace the list, so nothing repeats.
      source.addEventListener('backlog', (e) => {
        feed.value = JSON.parse((e as MessageEvent).data)
      })
      source.addEventListener('feed', (e) => {
        const steps: FeedStep[] = JSON.parse((e as MessageEvent).data)
        feed.value = [...feed.value, ...steps].slice(-FEED_KEEP)
      })
    },
    { immediate: true },
  )
  onScopeDispose(close)
  return { state, feed, connected }
}
