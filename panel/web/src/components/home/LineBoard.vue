<script setup lang="ts">
import { ChevronDown, Maximize, Minus, Plus } from 'lucide-vue-next'
import { useElementSize } from '@vueuse/core'
import { computed, ref, useTemplateRef, watch } from 'vue'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useProject } from '@/composables/useProject'
import { fitZoom, useLineView } from '@/lib/flow'
import { money, STAGE_NAMES } from '@/lib/format'
import FilesCard from './FilesCard.vue'
import JobCard from './JobCard.vue'
import LineGraph from './LineGraph.vue'
import NextStopCard from './NextStopCard.vue'

const { id, state } = useProject()
const jobs = computed(() => state.value?.jobs ?? [])

// The job the line follows: the person's pick, else the first that is running or waiting, else the newest.
const picked = ref<string | null>(null)
watch(id, () => (picked.value = null))
const focus = computed(() => jobs.value.find((j) => j.id === picked.value) ?? jobs.value[0] ?? null)

// Clicking a stage follows a job that is there: the one running or waiting first.
function pickAt(node: string) {
  const here = jobs.value.filter((j) => j.node === node)
  const best = here.find((j) => j.active) ?? here.find((j) => j.waiting) ?? here[0]
  if (best) picked.value = best.id
}

// One zoom for the whole board: the line zooms in its canvas, the cards scale with it, relative to the framed line.
const graph = useTemplateRef<{ fit: (duration?: number) => void }>('graph')
const view = useLineView(() => state.value?.line.length ?? 7)
const zoom = computed(() => Math.round(view.viewport.value.zoom * 100))
const cardScale = computed(() => Math.min(2, Math.max(0.5, view.viewport.value.zoom / fitZoom.value)))
// The cards are laid out once at full size and scaled as a picture, so their proportions hold at any zoom.
const stageSize = useElementSize(useTemplateRef<HTMLElement>('stage'))

// The next-stop card only says something while the job still moves or waits.
const hasStop = computed(() => !!focus.value && (focus.value.active || !!focus.value.waiting))

const summary = computed(() => {
  const t = state.value?.totals
  if (!t) return ''
  return `${jobs.value.length} jobs · ${t.merged} mesclados · ${t.active} ativos · ${t.waiting} esperando`
})
</script>

<template>
  <section
    class="relative flex min-h-0 flex-col overflow-hidden rounded-xl border bg-canvas bg-[radial-gradient(var(--dot)_1px,transparent_1.3px)] bg-[length:20px_20px]"
    aria-label="A linha"
  >
    <div class="flex h-14 flex-none items-center gap-3 border-b border-hairline bg-card pr-3.5 pl-5">
      <div class="flex min-w-0 items-baseline gap-2.5">
        <b class="text-[15px] font-semibold whitespace-nowrap">A linha</b>
        <span class="truncate text-xs text-faint" :title="summary">{{ summary }}</span>
      </div>
      <div class="ml-auto flex flex-none items-center gap-3.5 text-xs whitespace-nowrap text-muted-foreground">
        <span class="inline-flex items-center gap-1.5"><i class="size-2 rounded-full bg-agent" />agente</span>
        <span class="inline-flex items-center gap-1.5"><i class="size-2 rounded-full bg-faint" />núcleo</span>
        <span class="inline-flex items-center gap-1.5">
          <svg width="22" height="8" aria-hidden="true"><path d="M1 4h20" stroke-dasharray="4 3" class="stroke-loop" stroke-width="1.5" /></svg>volta
        </span>
      </div>
      <span class="mx-0.5 h-5 w-px bg-hairline" />
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button variant="outline" size="sm" class="h-[30px] gap-1.5 text-[12.5px] font-normal text-muted-foreground" :disabled="!jobs.length">
            Destacar <b class="font-semibold text-foreground">{{ focus ? `#${focus.issue}` : '—' }}</b>
            <ChevronDown class="size-3" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" class="w-80">
          <DropdownMenuLabel class="text-xs text-faint">Jobs deste projeto</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem v-for="j in jobs" :key="j.id" class="gap-2" @select="picked = j.id">
            <span class="w-8 font-mono text-xs text-faint">#{{ j.issue }}</span>
            <span class="flex-1 truncate">{{ j.title }}</span>
            <span class="text-[11px] text-faint">{{ STAGE_NAMES[j.stage] }} · {{ money(j.cost_usd) }}</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <div class="inline-flex h-[30px] overflow-hidden rounded-md border text-muted-foreground" role="group" aria-label="Zoom">
        <button class="flex w-[30px] items-center justify-center hover:bg-accent hover:text-foreground" aria-label="Diminuir" @click="view.zoomOut({ duration: 150 })">
          <Minus class="size-3.5" />
        </button>
        <span class="flex min-w-[46px] items-center justify-center border-x border-hairline font-mono text-[11px] tabular-nums">{{ zoom }}%</span>
        <button class="flex w-[30px] items-center justify-center hover:bg-accent hover:text-foreground" aria-label="Aumentar" @click="view.zoomIn({ duration: 150 })">
          <Plus class="size-3.5" />
        </button>
        <button class="flex w-[30px] items-center justify-center border-l border-hairline hover:bg-accent hover:text-foreground" title="Mostrar a linha inteira" @click="graph?.fit(200)">
          <Maximize class="size-3.5" />
        </button>
      </div>
    </div>

    <template v-if="state && jobs.length">
      <div class="min-h-[240px] flex-1 px-4 pt-2">
        <LineGraph ref="graph" :line="state.line" :loops="state.loops" :jobs="jobs" :focus="focus" @pick="pickAt" />
      </div>
      <div v-if="focus" ref="stage" class="relative min-h-[260px] flex-[0_1_420px]" :class="cardScale > 1 ? 'overflow-auto' : 'overflow-hidden'">
        <div
          class="grid origin-top-left grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] items-stretch gap-4 px-4 pb-4"
          :style="{
            width: `${stageSize.width.value}px`,
            height: `${stageSize.height.value}px`,
            transform: `translateX(${Math.max(0, (stageSize.width.value * (1 - cardScale)) / 2)}px) scale(${cardScale})`,
          }"
        >
          <JobCard :job="focus" :line="state.line" />
          <div class="flex min-h-0 flex-col gap-4">
            <NextStopCard v-if="hasStop" :job="focus" :line="state.line" class="flex-none" />
            <FilesCard :project="id" :job="focus" class="min-h-0 flex-1" />
          </div>
        </div>
      </div>
    </template>
    <div v-else-if="state" class="flex flex-1 items-center justify-center p-10 text-center">
      <div class="max-w-sm">
        <b class="text-sm font-semibold">Nenhum job ainda</b>
        <p class="mt-1 text-[13px] text-muted-foreground">
          Marque uma issue com a label <span class="font-mono text-xs">{{ state.project.label ?? 'puxirum' }}</span> e rode a fila
          (<span class="font-mono text-xs">/puxirum</span> no Claude Code, ou <span class="font-mono text-xs">puxirum run</span>).
        </p>
      </div>
    </div>
    <div v-else class="flex flex-1 items-center justify-center text-sm text-faint">Carregando…</div>
  </section>
</template>
