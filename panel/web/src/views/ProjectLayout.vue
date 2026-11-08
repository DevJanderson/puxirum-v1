<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import TabsNav from '@/components/TabsNav.vue'
import { provideProject } from '@/composables/useProject'
import { useProjectLive } from '@/lib/api'

const route = useRoute()
const id = computed(() => String(route.params.project))
const { state, feed, connected } = useProjectLive(id)
provideProject({ id, state, feed, connected })
</script>

<template>
  <!-- Exactly the window's height: a tab fills what is left, and the page scrolls only when the window is too short. -->
  <div class="flex h-dvh flex-col overflow-y-auto">
    <AppHeader />
    <TabsNav :project="id" />
    <div v-if="state?.problem" class="mx-6 mt-4 rounded-lg border border-destructive/30 bg-danger-subtle px-4 py-2 text-sm text-danger-text">
      {{ state.problem }}
    </div>
    <RouterView />
  </div>
</template>
