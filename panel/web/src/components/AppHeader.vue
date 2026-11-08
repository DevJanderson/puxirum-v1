<script setup lang="ts">
import { Moon, Sun } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TabsNav from '@/components/TabsNav.vue'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select'
import { useProject } from '@/composables/useProject'
import { useTheme } from '@/composables/useTheme'
import { fetchProjects, type ProjectRef } from '@/lib/api'

const { id, state, connected } = useProject()
const { toggle } = useTheme()
const route = useRoute()
const router = useRouter()
const projects = ref<ProjectRef[]>([])
onMounted(async () => {
  projects.value = await fetchProjects().catch(() => [])
})

const current = computed({
  get: () => id.value,
  set: (next: string) => {
    const tab = route.path.split('/')[2] ?? ''
    router.push(`/${next}/${tab}`)
  },
})
const name = computed(() => state.value?.project.name ?? id.value)
const branch = computed(() => state.value?.project.branch)
</script>

<template>
  <!-- One row: the project, the tabs, then the live dot (the name and mascot head the agents' side). The bottom line is
       an inset shadow, so the active tab's underline covers it without overflowing. It sits 12px down, like the
       agents' card, so both heads share a centre line and a bottom line. -->
  <header class="mt-3 mr-3 ml-6 flex h-14 flex-none items-stretch gap-4 shadow-[inset_0_-1px_0_var(--hairline)]">
    <div class="flex flex-none items-center gap-2.5">
      <Select v-model="current">
        <SelectTrigger
          size="sm"
          class="-ml-2 h-8 gap-2 border-0 bg-transparent px-2 text-[13px] text-muted-foreground shadow-none hover:bg-accent dark:bg-transparent dark:hover:bg-accent"
          aria-label="Projeto"
        >
          <b class="text-[15px] font-semibold tracking-tight text-foreground">{{ name }}</b>
          <span v-if="branch" class="rounded bg-neutral-subtle px-1.5 font-mono text-[11px] leading-[18px] text-neutral-text">{{ branch }}</span>
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</SelectItem>
        </SelectContent>
      </Select>
    </div>
    <TabsNav :project="id" class="flex-1" />
    <div class="flex flex-none items-center gap-2">
      <span class="flex items-center gap-1.5 text-xs text-muted-foreground" :title="connected ? 'recebendo atualizações' : 'reconectando'">
        <span class="size-1.5 rounded-full" :class="connected ? 'bg-success' : 'bg-faint'" />
        {{ connected ? 'ao vivo' : 'reconectando…' }}
      </span>
      <Button variant="ghost" size="icon" class="-mr-1.5 size-7 text-muted-foreground" aria-label="Trocar tema" @click="toggle">
        <Sun class="size-4 dark:hidden" />
        <Moon class="hidden size-4 dark:block" />
      </Button>
    </div>
  </header>
</template>
