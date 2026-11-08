<script setup lang="ts">
import { Moon, Sun } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PuxirumMark from '@/components/PuxirumMark.vue'
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
  <header class="flex items-center justify-between gap-4 px-6 pt-3.5">
    <div class="flex items-center gap-2.5">
      <PuxirumMark />
      <h1 class="text-[17px] leading-none font-semibold tracking-tight">Puxirum</h1>
      <Select v-model="current">
        <SelectTrigger
          size="sm"
          class="ml-1.5 h-7 gap-1.5 border-0 bg-transparent px-2 text-[13px] text-muted-foreground shadow-none hover:bg-accent dark:bg-transparent dark:hover:bg-accent"
          aria-label="Projeto"
        >
          projeto <b class="font-semibold text-foreground">{{ name }}</b>
          <span v-if="branch" class="rounded bg-neutral-subtle px-1.5 font-mono text-xs text-neutral-text">{{ branch }}</span>
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</SelectItem>
        </SelectContent>
      </Select>
    </div>
    <div class="flex items-center gap-2">
      <span class="flex items-center gap-1.5 text-xs text-muted-foreground" :title="connected ? 'recebendo atualizações' : 'reconectando'">
        <span class="size-1.5 rounded-full" :class="connected ? 'bg-success' : 'bg-faint'" />
        {{ connected ? 'ao vivo' : 'reconectando…' }}
      </span>
      <Button variant="ghost" size="icon" class="size-7 text-muted-foreground" aria-label="Trocar tema" @click="toggle">
        <Sun class="size-4 dark:hidden" />
        <Moon class="hidden size-4 dark:block" />
      </Button>
    </div>
  </header>
</template>
