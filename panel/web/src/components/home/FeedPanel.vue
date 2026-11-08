<script setup lang="ts">
import { useElementSize } from '@vueuse/core'
import { TerminalSquare } from 'lucide-vue-next'
import { computed, nextTick, useTemplateRef, watch } from 'vue'
import PuxirumMark from '@/components/PuxirumMark.vue'
import { useProject } from '@/composables/useProject'
import { LENS_NAMES } from '@/lib/format'

const { state, feed } = useProject()

const running = computed(() =>
  (state.value?.jobs ?? []).flatMap((j) => j.running.map((a) => ({ job: j, agent: a }))),
)
const waiting = computed(() => (state.value?.jobs ?? []).filter((j) => j.waiting === 'you').length)

// Keep the newest step in view, like a terminal.
const list = useTemplateRef<HTMLElement>('list')
const { height } = useElementSize(list)
watch(
  () => [feed.value.length, height.value],
  async () => {
    await nextTick()
    list.value?.scrollTo({ top: list.value.scrollHeight })
  },
)

const tone = (who: string) => {
  const n = [...who.split(' ')[0]!].reduce((a, c) => a + c.charCodeAt(0), 0)
  return ['text-agent', 'text-success', 'text-approval', 'text-primary'][n % 4]
}
</script>

<template>
  <section class="flex min-h-0 flex-col overflow-hidden rounded-xl border bg-card" aria-label="Agentes ao vivo">
    <div class="flex h-14 flex-none items-center gap-2.5 border-b border-hairline px-5">
      <span class="flex size-8 flex-none items-center justify-center rounded-[9px] border border-hairline bg-canvas">
        <PuxirumMark :size="22" />
      </span>
      <b class="text-sm font-semibold">Agentes</b>
      <span v-if="running.length" class="inline-flex items-center gap-1.5 text-xs text-primary">
        <i class="size-1.5 animate-blink rounded-full bg-primary" /> {{ running.length }} trabalhando
      </span>
      <span v-else class="text-xs text-faint">nenhum trabalhando agora</span>
      <span
        v-if="waiting"
        class="ml-auto rounded-full bg-approval-subtle px-2 text-[11px] leading-[18px] font-medium text-approval-text"
        >{{ waiting }} aguarda{{ waiting === 1 ? '' : 'm' }} você</span
      >
    </div>

    <div v-if="running.length" class="flex-none space-y-2 border-b border-hairline p-3">
      <div
        v-for="r in running"
        :key="`${r.job.id}-${r.agent.role}-${r.agent.lens}`"
        class="rounded-xl border bg-card px-3.5 py-3 shadow-card"
      >
        <div class="flex items-center gap-2 text-[13px] font-semibold text-primary">
          <i class="size-2 flex-none animate-pulse rounded-full bg-primary" />
          #{{ r.job.issue }} · {{ r.agent.lens ? `revisor ${LENS_NAMES[r.agent.lens] ?? r.agent.lens}` : r.agent.role }}
          <span class="ml-auto text-[11.5px] font-normal text-faint">rodada {{ r.agent.round }}</span>
        </div>
        <p class="mt-1 truncate font-mono text-xs text-muted-foreground">{{ r.agent.doing ?? 'começando…' }}</p>
      </div>
    </div>

    <div ref="list" class="min-h-0 flex-1 overflow-y-auto px-4 py-3">
      <p v-if="!feed.length" class="py-6 text-center text-xs text-faint">
        Os passos de cada agente aparecem aqui, um por linha, enquanto eles trabalham.
      </p>
      <ol class="space-y-1">
        <li v-for="(s, i) in feed" :key="i" class="grid grid-cols-[52px_minmax(0,auto)_1fr] gap-2 font-mono text-[11.5px] leading-5">
          <span class="text-faint">{{ s.at }}</span>
          <span class="whitespace-nowrap" :class="tone(s.who)">{{ s.who }}</span>
          <span class="truncate text-muted-foreground" :title="s.text">{{ s.text }}</span>
        </li>
      </ol>
    </div>

    <div class="flex-none px-4 pt-2 pb-4">
      <div class="flex gap-2.5 rounded-xl border bg-card px-3.5 py-3 text-xs text-muted-foreground shadow-card">
        <TerminalSquare class="mt-0.5 size-4 flex-none text-faint" />
        <p>
          Para conversar com a fábrica, use o <b class="font-semibold text-foreground">/puxirum</b> no Claude Code:
          ver a fila, rodar, dar feedback ou criar uma issue.
        </p>
      </div>
    </div>
  </section>
</template>
