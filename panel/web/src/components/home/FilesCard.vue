<script setup lang="ts">
import { FileText } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { Card } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { fetchJobFile, type Job } from '@/lib/api'

const props = defineProps<{ project: string; job: Job }>()

// The newest round first, then the job's own files in the order they were made.
const ORDER = ['issue.md', 'intake.md', 'spec.md', 'build.md', 'decision.md']
const files = computed(() =>
  [...props.job.files].sort((a, b) => {
    const ra = a.path.match(/^round-(\d+)\//)?.[1]
    const rb = b.path.match(/^round-(\d+)\//)?.[1]
    if (ra || rb) return Number(rb ?? 0) - Number(ra ?? 0) || a.path.localeCompare(b.path)
    return ORDER.indexOf(a.path) - ORDER.indexOf(b.path)
  }),
)

const open = ref(false)
const path = ref('')
const text = ref('')
async function show(p: string) {
  path.value = p
  text.value = 'carregando…'
  open.value = true
  text.value = await fetchJobFile(props.project, props.job.id, p).catch((e) => String(e))
}
</script>

<template>
  <Card class="min-h-0 gap-0 rounded-xl px-5 py-[18px] shadow-card">
    <p class="text-[11px] font-semibold tracking-wider text-faint uppercase">Fica registrado</p>
    <ScrollArea class="mt-2 min-h-0 flex-1">
      <ul class="pr-3">
        <li v-for="f in files" :key="f.path" class="border-t border-hairline first:border-t-0">
          <button
            class="flex w-full items-center gap-2.5 py-[7px] text-left font-mono text-xs hover:text-primary"
            @click="show(f.path)"
          >
            <FileText class="size-3.5 flex-none text-faint" />
            {{ f.path.split('/').pop() }}
            <span class="ml-auto font-sans text-[11px] text-faint">{{ f.path.includes('/') ? f.path.split('/')[0] + '/' : 'job' }}</span>
          </button>
        </li>
      </ul>
      <p v-if="!files.length" class="py-2 text-xs text-faint">Nenhum arquivo ainda.</p>
    </ScrollArea>
  </Card>

  <Sheet v-model:open="open">
    <SheetContent class="w-full gap-0 sm:max-w-2xl">
      <SheetHeader>
        <SheetTitle class="font-mono text-sm">{{ path }}</SheetTitle>
        <SheetDescription>.puxirum/state/jobs/{{ job.id }}/</SheetDescription>
      </SheetHeader>
      <ScrollArea class="min-h-0 flex-1 px-4 pb-4">
        <pre class="pr-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">{{ text }}</pre>
      </ScrollArea>
    </SheetContent>
  </Sheet>
</template>
