<script setup lang="ts">
import { useResizeObserver } from '@vueuse/core'
import { computed, ref, useTemplateRef } from 'vue'
import { TABS } from '@/lib/tabs'

const props = defineProps<{ project: string }>()

// A thin divider between groups, as in the design: Visão | Fábrica | Produto | Melhoria.
const items = computed(() =>
  TABS.map((tab, i) => ({ tab, divider: i > 0 && TABS[i - 1]!.group !== tab.group, to: `/${props.project}/${tab.path}` })),
)

// Only when the tabs don't fit does the right edge fade, to show there are more to scroll to.
const nav = useTemplateRef<HTMLElement>('nav')
const overflowing = ref(false)
useResizeObserver(nav, () => {
  if (nav.value) overflowing.value = nav.value.scrollWidth > nav.value.clientWidth + 1
})
</script>

<template>
  <!-- It sits in the header, whose bottom line the active tab's underline covers. On a narrow window the tabs scroll
       sideways, and the right edge fades so the cut-off ones show there are more. -->
  <nav
    ref="nav"
    class="flex min-w-0 items-stretch overflow-x-auto overflow-y-hidden [scrollbar-width:none]"
    :class="overflowing && 'pr-6 [mask-image:linear-gradient(to_right,black_calc(100%-32px),transparent)]'"
    aria-label="Telas do painel"
  >
    <template v-for="item in items" :key="item.tab.path">
      <span v-if="item.divider" class="mx-1 h-4 w-px flex-none self-center bg-hairline" />
      <RouterLink
        :to="item.to"
        exact-active-class="is-active"
        class="relative inline-flex items-center gap-1 px-[5px] text-[13px] whitespace-nowrap text-muted-foreground hover:text-foreground [&.is-active]:font-medium [&.is-active]:text-foreground [&.is-active]:after:absolute [&.is-active]:after:inset-x-2 [&.is-active]:after:bottom-0 [&.is-active]:after:h-0.5 [&.is-active]:after:rounded [&.is-active]:after:bg-foreground"
      >
        <component :is="item.tab.icon" class="size-3.5 flex-none" :stroke-width="1.6" />
        {{ item.tab.name }}
      </RouterLink>
    </template>
  </nav>
</template>
