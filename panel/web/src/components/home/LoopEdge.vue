<script setup lang="ts">
import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from '@vue-flow/core'
import { computed } from 'vue'

export interface LoopData {
  label: string
  count: number
  level: number
}

// A way back: up from a later stage, left above the line, and down into an earlier one.
const props = defineProps<EdgeProps<LoopData>>()

const geometry = computed(() => {
  const r = 10
  const sx = props.sourceX + 10
  const tx = props.targetX - 10 + props.data.level * 14
  const y = Math.min(props.sourceY, props.targetY) - 34 - props.data.level * 30
  return {
    path: `M${sx} ${props.sourceY} V${y + r} Q${sx} ${y} ${sx - r} ${y} H${tx + r} Q${tx} ${y} ${tx} ${y + r} V${props.targetY - 2}`,
    x: (sx + tx) / 2,
    y,
  }
})
</script>

<template>
  <BaseEdge
    :id="id"
    :path="geometry.path"
    :marker-end="markerEnd"
    class="!stroke-loop"
    :class="{ 'opacity-35': !data.count }"
    :style="{ strokeWidth: 1.4, strokeDasharray: '5 4' }"
  />
  <EdgeLabelRenderer>
    <span
      class="nodrag nopan absolute rounded-full border border-danger-subtle bg-card px-2 text-[11.5px] leading-5 whitespace-nowrap text-loop"
      :class="{ 'opacity-60': !data.count }"
      :style="{ transform: `translate(-50%, -50%) translate(${geometry.x}px, ${geometry.y}px)` }"
    >
      {{ data.label }}<template v-if="data.count"> · {{ data.count }}×</template>
    </span>
  </EdgeLabelRenderer>
</template>
