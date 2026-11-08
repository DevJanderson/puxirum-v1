<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import type { Tab } from '@/lib/tabs'

const route = useRoute()
const tab = computed(() => route.meta.tab as Tab)
</script>

<template>
  <main class="mt-5 mr-3 mb-3 ml-6 flex flex-1 items-center justify-center rounded-xl border border-dashed bg-canvas p-10">
    <div class="max-w-md text-center">
      <component :is="tab.icon" class="mx-auto size-8 text-faint" :stroke-width="1.4" />
      <p class="mt-4 text-[11px] font-semibold tracking-wider text-faint uppercase">Em breve</p>
      <h2 class="mt-1 text-lg font-semibold">{{ tab.question }}</h2>
      <p class="mt-2 text-sm text-muted-foreground">{{ tab.shows }}</p>
      <p class="mt-3 text-xs text-faint">Vai ler de {{ tab.reads }}.</p>
    </div>
  </main>
</template>
