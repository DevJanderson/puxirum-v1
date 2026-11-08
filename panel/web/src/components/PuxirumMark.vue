<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 32 })
</script>

<template>
  <!-- The mascot from the panel's design in Doop: pixel art, so it is never smoothed. -->
  <img
    src="/mascot.svg"
    alt="Mascote do Puxirum"
    :width="size"
    :height="size"
    class="flex-none [image-rendering:pixelated]"
  />
</template>
