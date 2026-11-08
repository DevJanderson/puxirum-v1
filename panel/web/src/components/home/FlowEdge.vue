<script setup lang="ts">
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@vue-flow/core'
import { computed } from 'vue'

export interface FlowData {
  /** How the highlighted job relates to this step: walked, walking now, or not yet. */
  status: 'done' | 'active' | 'ahead'
  /** Jobs that ever took this step. */
  passed: number
}

const props = defineProps<EdgeProps<FlowData>>()

const geometry = computed(() => {
  const [path, x, y] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  })
  return { path, x, y }
})
</script>

<template>
  <BaseEdge
    :id="id"
    :path="geometry.path"
    :class="{ 'flow-edge-active': data.status === 'active' }"
    :style="{
      stroke: data.status === 'done' ? 'var(--success)' : data.status === 'active' ? 'var(--primary)' : 'var(--arrow)',
      strokeWidth: data.status === 'ahead' ? 1.6 : 2.2,
      strokeDasharray: data.status === 'active' ? '6 4' : undefined,
    }"
  />
  <EdgeLabelRenderer v-if="data.passed">
    <span
      class="nodrag nopan absolute text-[11px] font-medium whitespace-nowrap text-faint"
      :style="{ transform: `translate(-50%, -100%) translate(${geometry.x}px, ${geometry.y - 6}px)` }"
      :title="`${data.passed} job(s) passaram por aqui`"
    >
      {{ data.passed }} job{{ data.passed === 1 ? '' : 's' }}
    </span>
  </EdgeLabelRenderer>
</template>

<style>
.flow-edge-active {
  animation: flow-edge-run 0.8s linear infinite;
}
@keyframes flow-edge-run {
  to {
    stroke-dashoffset: -20;
  }
}
</style>
