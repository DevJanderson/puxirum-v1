import { inject, provide, type InjectionKey, type Ref } from 'vue'
import type { FeedStep, State } from '@/lib/api'

export interface ProjectContext {
  id: Ref<string>
  state: Ref<State | null>
  feed: Ref<FeedStep[]>
  connected: Ref<boolean>
}

const KEY: InjectionKey<ProjectContext> = Symbol('project')

export function provideProject(ctx: ProjectContext) {
  provide(KEY, ctx)
}

export function useProject(): ProjectContext {
  const ctx = inject(KEY)
  if (!ctx) throw new Error('useProject outside a project page')
  return ctx
}
