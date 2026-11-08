<script setup lang="ts">
import { Menu, Monitor, Moon, Sun } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TabsNav from '@/components/TabsNav.vue'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select'
import { useProject } from '@/composables/useProject'
import { useTheme } from '@/composables/useTheme'
import { fetchProjects, type ProjectRef } from '@/lib/api'

const { id, state, connected } = useProject()
const theme = useTheme()
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
  <!-- One row: the project, the tabs, then the menu (the name and mascot head the agents' side). It sits 12px down,
       like the agents' card, so both heads share a centre line. -->
  <header class="mt-3 mr-3 flex h-14 flex-none items-stretch gap-4 px-1">
    <div class="flex flex-none items-center gap-2.5">
      <Select v-model="current">
        <SelectTrigger
          size="sm"
          class="h-8 gap-2 border-0 bg-transparent px-2 text-[13px] text-muted-foreground shadow-none hover:bg-accent dark:bg-transparent dark:hover:bg-accent"
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
    <!-- The menu, for the panel's options (the theme, for now). Its dot says whether the page gets live updates. -->
    <div class="flex flex-none items-center">
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button
            variant="ghost"
            size="icon"
            class="relative size-8 text-muted-foreground"
            :aria-label="connected ? 'Menu (ao vivo)' : 'Menu (reconectando)'"
            :title="connected ? 'ao vivo: recebendo atualizações' : 'reconectando…'"
          >
            <Menu class="size-[18px]" />
            <span class="absolute top-1 right-1 size-1.5 rounded-full ring-2 ring-background" :class="connected ? 'bg-success' : 'bg-faint'" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" class="w-48">
          <DropdownMenuLabel class="text-xs font-normal text-faint">Tema</DropdownMenuLabel>
          <DropdownMenuRadioGroup :model-value="theme.choice.value" @update:model-value="(v) => theme.set(v as 'light' | 'dark' | 'system')">
            <DropdownMenuRadioItem value="light" class="gap-2"><Sun class="size-4" />Claro</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="dark" class="gap-2"><Moon class="size-4" />Escuro</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="system" class="gap-2"><Monitor class="size-4" />Do sistema</DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  </header>
</template>
