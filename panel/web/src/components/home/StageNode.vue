<script setup lang="ts">
import { Handle, Position, type NodeProps } from '@vue-flow/core'
import { Check, Clock, Code, Eye, FileCheck, FileText, FlaskConical, GitMerge, Inbox, X } from 'lucide-vue-next'
import type { Component } from 'vue'
import type { LineNode } from '@/lib/api'

/** Where the highlighted job is relative to this stage. */
export type StageStatus = 'done' | 'running' | 'here' | 'waiting' | 'stopped' | 'ahead'

export interface StageData {
  node: LineNode
  index: number
  status: StageStatus
  others: number
  merged: number
  chip: string | null
}

defineProps<NodeProps<StageData>>()

const ICONS: Record<string, Component> = {
  intake: Inbox,
  spec: FileText,
  build: Code,
  gate: FlaskConical,
  review: Eye,
  approve: FileCheck,
  merge: GitMerge,
}
</script>

<template>
  <div class="group flex w-[140px] cursor-pointer flex-col items-center text-center">
    <div class="relative">
      <!-- The stage where an agent is working now pulses. -->
      <div
        class="relative flex size-[84px] items-center justify-center rounded-[18px] border-2 bg-card shadow-card transition-[border-color,box-shadow] group-hover:shadow-md"
        :class="{
          'animate-pulse-ring': data.status === 'running',
          'border-success': data.status === 'done',
          'border-primary': data.status === 'running' || data.status === 'here',
          'border-approval': data.status === 'waiting',
          'border-destructive/60': data.status === 'stopped',
          'border-border group-hover:border-primary/50': data.status === 'ahead',
          'text-agent': data.node.kind === 'agent',
          'text-muted-foreground': data.node.kind === 'core',
        }"
      >
        <Handle id="in" type="target" :position="Position.Left" class="stage-port" />
        <Handle id="out" type="source" :position="Position.Right" class="stage-port" />
        <Handle id="top-out" type="source" :position="Position.Top" class="stage-anchor" />
        <Handle id="top-in" type="target" :position="Position.Top" class="stage-anchor" />

        <span class="absolute top-1.5 left-2.5 font-mono text-[10.5px] text-faint">{{ data.index + 1 }}</span>
        <component :is="ICONS[data.node.id]" class="size-9" :stroke-width="1.5" />

        <span
          v-if="data.status === 'done'"
          class="absolute -right-2 -bottom-2 flex size-[22px] items-center justify-center rounded-full bg-success text-primary-foreground ring-[3px] ring-canvas"
          ><Check class="size-3.5" :stroke-width="3"
        /></span>
        <span
          v-else-if="data.status === 'waiting'"
          class="absolute -right-2 -bottom-2 flex size-[22px] items-center justify-center rounded-full bg-approval text-primary-foreground ring-[3px] ring-canvas"
          ><Clock class="size-3.5" :stroke-width="2.6"
        /></span>
        <span
          v-else-if="data.status === 'stopped'"
          class="absolute -right-2 -bottom-2 flex size-[22px] items-center justify-center rounded-full bg-destructive text-primary-foreground ring-[3px] ring-canvas"
          ><X class="size-3.5" :stroke-width="3"
        /></span>
        <span
          v-if="data.others"
          class="absolute -top-2 -right-2 min-w-[22px] rounded-full bg-neutral-subtle px-1.5 text-[11px] leading-[22px] font-semibold text-neutral-text ring-[3px] ring-canvas"
          :title="`mais ${data.others} job(s) nesta etapa`"
          >+{{ data.others }}</span
        >
      </div>
    </div>
    <b class="mt-3 text-[13.5px] leading-tight font-semibold">{{ data.node.name }}</b>
    <span class="mt-0.5 font-mono text-[11px] text-faint">{{ data.node.files }}</span>
    <span
      v-if="data.chip"
      class="mt-2 rounded-full px-2.5 text-[11px] leading-5 font-semibold whitespace-nowrap"
      :class="{
        'bg-primary text-primary-foreground': data.status === 'running' || data.status === 'here',
        'bg-approval-subtle text-approval-text': data.status === 'waiting',
        'bg-neutral-subtle text-muted-foreground': data.status === 'stopped',
      }"
      >{{ data.chip }}</span
    >
    <span
      v-else-if="data.merged"
      class="mt-2 rounded-full bg-success-subtle px-2.5 text-[11px] leading-5 font-semibold text-success-text"
      >{{ data.merged }} mesclado{{ data.merged === 1 ? '' : 's' }}</span
    >
  </div>
</template>

<style>
/* n8n-like ports: a small ring on each side; the top anchors only carry the ways back. */
.vue-flow__handle.stage-port {
  border-radius: 999px;
  width: 10px;
  height: 10px;
  min-width: 10px;
  min-height: 10px;
  background: var(--card);
  border: 2px solid var(--arrow);
}
.vue-flow__handle.stage-anchor {
  opacity: 0;
}
</style>
