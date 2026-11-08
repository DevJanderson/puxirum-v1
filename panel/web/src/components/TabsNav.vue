<script setup lang="ts">
import { computed } from 'vue'
import { TABS } from '@/lib/tabs'

const props = defineProps<{ project: string }>()

// A thin divider between groups, as in the design: Visão | Fábrica | Produto | Melhoria.
const items = computed(() =>
  TABS.map((tab, i) => ({ tab, divider: i > 0 && TABS[i - 1]!.group !== tab.group, to: `/${props.project}/${tab.path}` })),
)
</script>

<template>
  <!-- The line under the tabs is an inset shadow, so the active tab's underline covers it without overflowing. -->
  <nav
    class="mx-6 mt-3 flex flex-none items-center gap-0.5 overflow-x-auto overflow-y-hidden shadow-[inset_0_-1px_0_var(--hairline)] [scrollbar-width:none]"
    aria-label="Telas do painel"
  >
    <template v-for="item in items" :key="item.tab.path">
      <span v-if="item.divider" class="mx-1 h-4 w-px flex-none bg-hairline" />
      <RouterLink
        :to="item.to"
        exact-active-class="is-active"
        class="relative inline-flex items-center gap-1.5 rounded-t-md px-1.5 pt-2 pb-2.5 text-[13px] whitespace-nowrap text-muted-foreground hover:text-foreground [&.is-active]:font-medium [&.is-active]:text-foreground [&.is-active]:after:absolute [&.is-active]:after:inset-x-2 [&.is-active]:after:bottom-0 [&.is-active]:after:h-0.5 [&.is-active]:after:rounded [&.is-active]:after:bg-foreground"
      >
        <component :is="item.tab.icon" class="size-4 flex-none" :stroke-width="1.6" />
        {{ item.tab.name }}
      </RouterLink>
    </template>
  </nav>
</template>
