<script setup lang="ts">
import { MarkerType, VueFlow, type Edge, type Node } from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import { useResizeObserver } from '@vueuse/core'
import { computed, markRaw, useTemplateRef } from 'vue'
import type { Job, LineNode, Loop } from '@/lib/api'
import { LINE_FLOW, SPACING, useLineView } from '@/lib/flow'
import FlowEdge, { type FlowData } from './FlowEdge.vue'
import LoopEdge, { type LoopData } from './LoopEdge.vue'
import StageNode, { type StageData, type StageStatus } from './StageNode.vue'

const props = defineProps<{ line: LineNode[]; loops: Loop[]; jobs: Job[]; focus: Job | null }>()
const emit = defineEmits<{ pick: [node: string] }>()

const nodeTypes = { stage: markRaw(StageNode) }
const edgeTypes = { flow: markRaw(FlowEdge), loop: markRaw(LoopEdge) }

const nodeOf = computed(() => {
  const map: Record<string, string> = {}
  for (const n of props.line) for (const s of n.stages) map[s] = n.id
  return map
})
const at = computed(() => (props.focus ? props.line.findIndex((n) => n.id === props.focus!.node) : -1))

function status(index: number): StageStatus {
  const j = props.focus
  if (!j || at.value < 0) return 'ahead'
  if (j.stage === 'merged' || index < at.value) return 'done'
  if (index > at.value) return 'ahead'
  if (j.stage === 'rejected') return 'stopped'
  if (j.waiting) return 'waiting'
  return j.running.length ? 'running' : 'here'
}

const chip = computed(() => {
  const j = props.focus
  if (!j || j.stage === 'merged') return null
  if (j.waiting === 'you') return `#${j.issue} · aguarda você`
  if (j.waiting === 'author') return `#${j.issue} · aguarda o autor`
  if (j.stage === 'rejected') return `#${j.issue} · rejeitado`
  return `#${j.issue}${j.round ? ` · rodada ${j.round}` : ''}`
})

// How many jobs ever took each step forward, from every job's transitions.
const passed = computed(() => {
  const count: Record<string, number> = {}
  for (const j of props.jobs) {
    for (const t of j.timeline) {
      const a = nodeOf.value[t.from]
      const b = nodeOf.value[t.to]
      if (a && b && a !== b) count[`${a}-${b}`] = (count[`${a}-${b}`] ?? 0) + 1
    }
  }
  return count
})

const nodes = computed<Node<StageData>[]>(() =>
  props.line.map((node, index) => {
    const here = props.jobs.filter((j) => j.node === node.id && j.stage !== 'merged' && j.stage !== 'rejected')
    const s = status(index)
    return {
      id: node.id,
      type: 'stage',
      position: { x: index * SPACING, y: 0 },
      data: {
        node,
        index,
        status: s,
        others: here.filter((j) => j.id !== props.focus?.id).length,
        merged: node.id === 'merge' ? props.jobs.filter((j) => j.stage === 'merged').length : 0,
        chip: index === at.value ? chip.value : null,
      },
    }
  }),
)

const edges = computed<Edge[]>(() => [
  ...props.line.slice(1).map((node, i): Edge<FlowData> => {
    const done = status(i + 1) === 'done' || (status(i) === 'done' && status(i + 1) !== 'ahead')
    const active = status(i) === 'done' && ['running', 'here'].includes(status(i + 1))
    return {
      id: `${props.line[i]!.id}-${node.id}`,
      source: props.line[i]!.id,
      target: node.id,
      sourceHandle: 'out',
      targetHandle: 'in',
      type: 'flow',
      data: { status: active ? 'active' : done ? 'done' : 'ahead', passed: passed.value[`${props.line[i]!.id}-${node.id}`] ?? 0 },
    }
  }),
  ...props.loops.map(
    (loop, level): Edge<LoopData> => ({
      id: `loop-${loop.id}`,
      source: loop.from,
      target: loop.to,
      sourceHandle: 'top-out',
      targetHandle: 'top-in',
      type: 'loop',
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: 'var(--loop)' },
      data: { label: loop.label, count: loop.count, level },
    }),
  ),
])

const view = useLineView(() => props.line.length)
const box = useTemplateRef<HTMLElement>('box')
const fit = (duration = 0) => box.value && view.fit(box.value.clientWidth, box.value.clientHeight, duration)
useResizeObserver(box, () => fit())
defineExpose({ fit })
</script>

<template>
  <div ref="box" class="h-full">
    <VueFlow
      :id="LINE_FLOW"
      :nodes="nodes"
      :edges="edges"
      :node-types="nodeTypes"
      :edge-types="edgeTypes"
      :nodes-draggable="false"
      :nodes-connectable="false"
      :elements-selectable="false"
      :zoom-on-scroll="false"
      :zoom-on-double-click="false"
      :prevent-scrolling="false"
      :min-zoom="0.4"
      :max-zoom="2"
      @pane-ready="fit()"
      @nodes-initialized="fit()"
      @node-click="({ node }) => emit('pick', node.id)"
    >
    </VueFlow>
  </div>
</template>

<style>
.vue-flow__node-stage {
  background: transparent;
  border: 0;
  padding: 0;
}
</style>
