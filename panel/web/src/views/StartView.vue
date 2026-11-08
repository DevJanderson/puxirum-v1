<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PuxirumMark from '@/components/PuxirumMark.vue'
import { fetchProjects, type ProjectRef } from '@/lib/api'

const router = useRouter()
const projects = ref<ProjectRef[] | null>(null)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    projects.value = await fetchProjects()
    if (projects.value.length === 1) router.replace(`/${projects.value[0]!.id}`)
  } catch (e) {
    error.value = String(e)
  }
})
</script>

<template>
  <main class="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-6 px-6">
    <div class="flex items-center gap-3">
      <PuxirumMark />
      <h1 class="text-lg font-semibold">Puxirum</h1>
    </div>
    <p v-if="error" class="text-sm text-destructive">Não consegui falar com o servidor do painel: {{ error }}</p>
    <p v-else-if="projects === null" class="text-sm text-muted-foreground">Procurando projetos…</p>
    <div v-else-if="projects.length === 0" class="space-y-2 text-sm text-muted-foreground">
      <p>Nenhum repositório com o Puxirum instalado foi encontrado.</p>
      <p>Rode <code class="font-mono text-foreground">puxirum init</code> num projeto, ou aponte o painel para a pasta deles com <code class="font-mono text-foreground">--projects</code>.</p>
    </div>
    <nav v-else class="flex flex-col gap-1">
      <p class="mb-2 text-sm text-muted-foreground">Escolha um projeto</p>
      <RouterLink
        v-for="p in projects"
        :key="p.id"
        :to="`/${p.id}`"
        class="flex items-center justify-between rounded-lg border px-4 py-3 hover:bg-accent"
      >
        <span class="font-medium">{{ p.name }}</span>
        <span v-if="p.branch" class="rounded bg-neutral-subtle px-1.5 font-mono text-xs text-neutral-text">{{ p.branch }}</span>
      </RouterLink>
    </nav>
  </main>
</template>
