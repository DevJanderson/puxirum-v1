<script setup lang="ts">
import FeedPanel from '@/components/home/FeedPanel.vue'
import LineBoard from '@/components/home/LineBoard.vue'
</script>

<template>
  <main class="mx-6 mt-5 mb-6 grid min-h-[640px] flex-1 grid-cols-[400px_minmax(0,1fr)] gap-4 max-lg:flex-none max-lg:grid-cols-1">
    <FeedPanel class="max-lg:h-[420px]" />
    <LineBoard />
  </main>
</template>
