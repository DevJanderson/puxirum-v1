<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import FeedPanel from '@/components/home/FeedPanel.vue'
import { provideProject } from '@/composables/useProject'
import { useProjectLive } from '@/lib/api'

const route = useRoute()
const id = computed(() => String(route.params.project))
const { state, feed, connected } = useProjectLive(id)
provideProject({ id, state, feed, connected })
</script>

<template>
  <!-- The agents run down the whole left side, on every tab. Beside them, exactly the window's height: a tab fills what
       is left, and only that side scrolls when the window is too short. -->
  <div class="flex h-dvh">
    <FeedPanel />
    <div class="flex min-w-0 flex-1 flex-col overflow-y-auto">
      <AppHeader />
      <div v-if="state?.problem" class="mt-4 mr-3 rounded-lg border border-destructive/30 bg-danger-subtle px-4 py-2 text-sm text-danger-text">
        {{ state.problem }}
      </div>
      <RouterView />
    </div>
  </div>
</template>
