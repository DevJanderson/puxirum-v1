<script setup lang="ts">
import { Check, CircleDashed, ExternalLink, X } from 'lucide-vue-next'
import { computed } from 'vue'
import { Card } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { Job, LineNode } from '@/lib/api'
import { duration, LENS_NAMES, money, STAGE_NAMES } from '@/lib/format'

const props = defineProps<{ job: Job; line: LineNode[] }>()

const at = computed(() => props.line.findIndex((n) => n.id === props.job.node))
const merged = computed(() => props.job.stage === 'merged')
const progress = computed(() => (merged.value ? 100 : Math.round((at.value / props.line.length) * 100)))
const lastRound = computed(() => props.job.rounds[props.job.rounds.length - 1] ?? null)

type Status = 'done' | 'now' | 'wait' | 'todo' | 'stopped'

function status(i: number): Status {
  if (merged.value || i < at.value) return 'done'
  if (i > at.value) return 'todo'
  if (props.job.stage === 'rejected') return 'stopped'
  if (props.job.waiting) return 'wait'
  return 'now'
}

function detail(node: LineNode): string {
  const j = props.job
  switch (node.id) {
    case 'intake':
      return j.loops.questions ? `${j.loops.questions}× perguntou ao autor` : j.risk ? `risco ${j.risk}` : 'lê a issue e decide'
    case 'spec':
      return 'o que vai ser construído e como conferir'
    case 'build':
      return j.round ? `rodada ${j.round} de ${j.round_limit}` : 'implementa no branch do job'
    case 'gate':
      return lastRound.value?.gate ? `checks.sh: ${lastRound.value.gate}` : 'roda o checks.sh do projeto'
    case 'review': {
      const lenses = Object.keys(j.reviewers)
      return lenses.length ? lenses.map((l) => LENS_NAMES[l] ?? l).join(', ') : 'lentes por risco e superfície'
    }
    case 'approve':
      return 'decide se mescla'
    case 'merge':
      return j.pr ? `PR #${j.pr}` : 'o núcleo abre e mescla o PR'
    default:
      return node.files
  }
}

const stateChip = computed(() => {
  const j = props.job
  if (j.running.length) return { text: 'trabalhando', tone: 'now' }
  if (j.waiting === 'you') return { text: 'aguarda você', tone: 'approval' }
  if (j.waiting === 'author') return { text: 'aguarda o autor', tone: 'approval' }
  if (j.stage === 'merged') return { text: 'mesclado', tone: 'success' }
  if (j.stage === 'rejected') return { text: 'rejeitado', tone: 'neutral' }
  return { text: STAGE_NAMES[j.stage] ?? j.stage, tone: 'neutral' }
})

function verdictTone(v: string | null | undefined) {
  if (!v) return 'bg-neutral-subtle text-muted-foreground'
  return v === 'PASS' ? 'bg-success-subtle text-success-text' : 'bg-danger-subtle text-danger-text'
}
</script>

<template>
  <Card class="min-h-0 gap-0 rounded-xl px-5 py-[18px] shadow-card">
    <div class="flex items-center gap-2.5">
      <div class="flex min-w-0 flex-col leading-snug">
        <b class="truncate text-sm font-semibold">#{{ job.issue }} · {{ job.title }}</b>
        <span class="text-xs text-faint">
          {{ job.id }} · {{ money(job.cost_usd) }} · {{ duration(job.active_seconds) }} ativo
        </span>
      </div>
      <span
        class="ml-auto inline-flex flex-none items-center gap-1.5 rounded-full px-2 text-[11px] leading-[18px] whitespace-nowrap"
        :class="{
          'bg-primary font-semibold text-primary-foreground': stateChip.tone === 'now',
          'bg-approval-subtle font-medium text-approval-text': stateChip.tone === 'approval',
          'bg-success-subtle font-medium text-success-text': stateChip.tone === 'success',
          'bg-neutral-subtle text-muted-foreground': stateChip.tone === 'neutral',
        }"
      >
        <i v-if="stateChip.tone === 'now'" class="size-1.5 animate-pulse rounded-full bg-primary-foreground" />{{ stateChip.text }}
      </span>
    </div>

    <div class="mt-3.5 h-1 overflow-hidden rounded-sm bg-hairline">
      <i
        class="block h-full rounded-sm"
        :class="merged ? 'bg-success' : 'bg-primary'"
        :style="{ width: `${Math.max(progress, 4)}%` }"
      />
    </div>
    <div class="mt-1.5 flex justify-between text-[11.5px] text-faint">
      <span>etapa {{ Math.min(at + 1, line.length) }} de {{ line.length }}</span>
      <a v-if="job.pr_url" :href="job.pr_url" target="_blank" rel="noopener" class="inline-flex items-center gap-1 text-primary hover:underline">
        PR #{{ job.pr }} <ExternalLink class="size-3" />
      </a>
    </div>

    <ScrollArea class="mt-3 min-h-0 flex-1">
    <ol class="pr-3">
      <li
        v-for="(node, i) in line"
        :key="node.id"
        class="relative grid grid-cols-[22px_1fr] gap-3 pb-[7px] last:pb-0 [&:not(:last-child)]:before:absolute [&:not(:last-child)]:before:top-[26px] [&:not(:last-child)]:before:bottom-1 [&:not(:last-child)]:before:left-[10.25px] [&:not(:last-child)]:before:w-[1.5px]"
        :class="status(i) === 'done' ? '[&:not(:last-child)]:before:bg-success/50' : '[&:not(:last-child)]:before:bg-hairline'"
      >
        <span
          class="flex size-[22px] items-center justify-center rounded-full"
          :class="{
            'bg-success-subtle text-success': status(i) === 'done',
            'border-2 border-primary': status(i) === 'now',
            'bg-approval-subtle text-approval': status(i) === 'wait',
            'bg-neutral-subtle text-muted-foreground': status(i) === 'stopped',
            'text-faint': status(i) === 'todo',
          }"
        >
          <Check v-if="status(i) === 'done'" class="size-3" :stroke-width="2.4" />
          <i v-else-if="status(i) === 'now'" class="size-2 animate-pulse rounded-full bg-primary" />
          <X v-else-if="status(i) === 'stopped'" class="size-3" :stroke-width="2.4" />
          <CircleDashed v-else-if="status(i) === 'todo'" class="size-[22px]" :stroke-width="1.2" />
        </span>
        <div class="min-w-0">
          <b
            class="block text-[13px] leading-[22px] font-semibold"
            :class="{ 'text-primary': status(i) === 'now', 'font-medium text-muted-foreground': status(i) === 'todo' }"
            >{{ node.name }}</b
          >
          <p class="truncate text-xs" :class="status(i) === 'todo' ? 'text-faint' : 'text-muted-foreground'">{{ detail(node) }}</p>
          <div v-if="node.id === 'review' && lastRound && Object.keys(lastRound.reviews).length" class="mt-1.5 flex flex-wrap gap-1">
            <span
              v-for="(v, lens) in lastRound.reviews"
              :key="lens"
              class="rounded-full px-1.5 text-[10.5px] leading-4 font-medium"
              :class="verdictTone(v)"
              >{{ LENS_NAMES[lens] ?? lens }} {{ v ?? '…' }}</span
            >
          </div>
        </div>
      </li>
    </ol>
    </ScrollArea>
  </Card>
</template>
