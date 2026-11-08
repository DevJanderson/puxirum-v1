<script setup lang="ts">
import { useElementSize, useLocalStorage } from '@vueuse/core'
import { GripVertical, PanelLeftClose, PanelLeftOpen, TerminalSquare } from 'lucide-vue-next'
import { computed, nextTick, ref, useTemplateRef, watch } from 'vue'
import PuxirumMark from '@/components/PuxirumMark.vue'
import { useProject } from '@/composables/useProject'
import { LENS_NAMES } from '@/lib/format'

const { state, feed } = useProject()

// Folded down to a rail, remembered across tabs and visits.
const collapsed = useLocalStorage('puxirum-sidebar-collapsed', false)

// Its width, dragged from its right edge (or with the arrow keys there) and remembered; a double click restores it.
const WIDTH = { start: 380, min: 320, max: 760, step: 16 }
const width = useLocalStorage('puxirum-sidebar-width', WIDTH.start)
const clamp = (w: number) => Math.round(Math.min(WIDTH.max, Math.max(WIDTH.min, w, 0), window.innerWidth * 0.6))
const dragging = ref(false)
function startDrag(down: PointerEvent) {
  const handle = down.currentTarget as HTMLElement
  const from = { x: down.clientX, width: width.value }
  handle.setPointerCapture(down.pointerId)
  dragging.value = true
  document.body.classList.add('cursor-col-resize', 'select-none')
  const move = (e: PointerEvent) => (width.value = clamp(from.width + e.clientX - from.x))
  const stop = () => {
    dragging.value = false
    document.body.classList.remove('cursor-col-resize', 'select-none')
    handle.removeEventListener('pointermove', move)
    handle.removeEventListener('pointerup', stop)
    handle.removeEventListener('pointercancel', stop)
  }
  handle.addEventListener('pointermove', move)
  handle.addEventListener('pointerup', stop)
  handle.addEventListener('pointercancel', stop)
}

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
  <!-- Folded: a small rail, only as tall as what it holds, 12px from the edge and from the page, with the way back
       open and a pulse while agents work. -->
  <aside
    v-if="collapsed"
    class="mx-3 mt-3 flex w-12 flex-none flex-col items-center gap-2 self-start rounded-xl border bg-card py-2"
    aria-label="Agentes ao vivo"
  >
    <button
      class="flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
      title="Abrir os agentes"
      @click="collapsed = false"
    >
      <PanelLeftOpen class="size-4" />
    </button>
    <button
      class="relative flex size-9 items-center justify-center rounded-[10px] border border-hairline bg-canvas"
      :title="running.length ? `${running.length} trabalhando` : 'nenhum trabalhando agora'"
      @click="collapsed = false"
    >
      <PuxirumMark :size="24" />
      <span
        v-if="running.length"
        class="absolute -top-1 -right-1 flex size-4 items-center justify-center rounded-full bg-primary text-[10px] font-semibold text-primary-foreground ring-2 ring-card"
        >{{ running.length }}</span
      >
    </button>
    <i v-if="running.length" class="size-2 animate-pulse rounded-full bg-primary" />
    <span
      v-if="waiting"
      class="rounded-full bg-approval-subtle px-1.5 text-[10.5px] leading-4 font-medium text-approval-text"
      :title="`${waiting} aguarda${waiting === 1 ? '' : 'm'} você`"
      >{{ waiting }}</span
    >
  </aside>

  <aside
    v-else
    class="my-3 ml-3 flex flex-none flex-col overflow-hidden rounded-xl border bg-card"
    :style="{ width: `${clamp(width)}px` }"
    aria-label="Agentes ao vivo"
  >
    <div class="flex h-14 flex-none items-center gap-2.5 border-b border-hairline pr-3 pl-5">
      <span class="flex size-8 flex-none items-center justify-center rounded-[9px] border border-hairline bg-canvas">
        <PuxirumMark :size="22" />
      </span>
      <h1 class="text-[15px] leading-none font-semibold tracking-tight">Puxirum</h1>
      <span v-if="running.length" class="inline-flex items-center gap-1.5 text-xs text-primary">
        <i class="size-1.5 animate-blink rounded-full bg-primary" /> {{ running.length }} trabalhando
      </span>
      <span v-else class="text-xs text-faint">nenhum trabalhando agora</span>
      <span
        v-if="waiting"
        class="ml-auto rounded-full bg-approval-subtle px-2 text-[11px] leading-[18px] font-medium text-approval-text"
        >{{ waiting }} aguarda{{ waiting === 1 ? '' : 'm' }} você</span
      >
      <button
        class="flex size-8 flex-none items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
        :class="!waiting && 'ml-auto'"
        title="Recolher os agentes"
        @click="collapsed = true"
      >
        <PanelLeftClose class="size-4" />
      </button>
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
  </aside>

  <!-- The gap to the page is the handle that sets the agents' width: a grip in the middle shows it can be dragged,
       sideways, or moved with the arrow keys once focused; a double click restores the width. Its 16px are the whole
       gap: the page has no left margin of its own, so nothing overlaps the handle. -->
  <div
    v-if="!collapsed"
    role="separator"
    aria-orientation="vertical"
    aria-label="Largura dos agentes"
    :aria-valuenow="clamp(width)"
    :aria-valuemin="WIDTH.min"
    :aria-valuemax="WIDTH.max"
    tabindex="0"
    title="Arraste para mudar a largura; dois cliques voltam ao padrão"
    class="group flex w-4 flex-none cursor-col-resize touch-none items-center justify-center outline-none"
    @pointerdown.prevent="startDrag"
    @dblclick="width = WIDTH.start"
    @keydown.left.prevent="width = clamp(width - WIDTH.step)"
    @keydown.right.prevent="width = clamp(width + WIDTH.step)"
  >
    <span
      class="flex h-8 w-3 items-center justify-center rounded-full text-faint transition-colors group-hover:bg-accent group-hover:text-foreground group-focus-visible:bg-accent group-focus-visible:text-foreground"
      :class="dragging && 'bg-accent text-foreground'"
    >
      <GripVertical class="size-3.5" />
    </span>
  </div>
</template>
