<script setup lang="ts">
import { CircleCheck, FileCheck, MessageCircleQuestion, Signpost } from 'lucide-vue-next'
import { computed } from 'vue'
import { Card } from '@/components/ui/card'
import type { Job, LineNode } from '@/lib/api'

const props = defineProps<{ job: Job; line: LineNode[] }>()

const next = computed(() => {
  const i = props.line.findIndex((n) => n.id === props.job.node)
  return props.line[i + 1] ?? null
})
</script>

<template>
  <Card class="gap-0 rounded-xl px-5 py-[18px] shadow-card">
    <template v-if="job.waiting === 'you'">
      <div class="flex items-center gap-2.5">
        <span class="flex size-[30px] flex-none items-center justify-center rounded-lg border-[1.5px] border-approval-border text-approval">
          <FileCheck class="size-4" />
        </span>
        <div class="flex flex-col leading-snug">
          <b class="text-sm font-semibold">Próxima parada: a sua decisão</b>
          <span class="text-xs text-faint">#{{ job.issue }} parou e espera por você</span>
        </div>
      </div>
      <p v-if="job.reason" class="mt-3 rounded-lg bg-approval-subtle px-3 py-2 text-[13px] text-approval-text">{{ job.reason }}</p>
      <ol class="mt-3 list-decimal space-y-1.5 pl-5 text-[13px]">
        <li>leia o motivo e a rodada que levou a ele (os arquivos ao lado);</li>
        <li>
          mande de volta com o que mudar:
          <code class="rounded bg-danger-subtle px-1 font-mono text-xs text-danger-text">puxirum feedback {{ job.issue }} -m "…"</code>
        </li>
        <li>
          ou encerre:
          <code class="rounded bg-danger-subtle px-1 font-mono text-xs text-danger-text">puxirum reject {{ job.issue }} -m "…"</code>
        </li>
      </ol>
      <p class="mt-3 border-t border-hairline pt-3 text-xs text-muted-foreground">
        No Claude Code, o <span class="font-mono">/puxirum</span> explica a escalada e repassa a sua escolha.
      </p>
    </template>

    <template v-else-if="job.waiting === 'author'">
      <div class="flex items-center gap-2.5">
        <span class="flex size-[30px] flex-none items-center justify-center rounded-lg border-[1.5px] border-approval-border text-approval">
          <MessageCircleQuestion class="size-4" />
        </span>
        <div class="flex flex-col leading-snug">
          <b class="text-sm font-semibold">Aguarda o autor da issue</b>
          <span class="text-xs text-faint">o intake fez perguntas na #{{ job.issue }}</span>
        </div>
      </div>
      <p class="mt-3 text-[13px]">
        Só o autor da issue responde. A próxima <span class="font-mono text-xs">puxirum run</span> lê a resposta e o intake decide de novo.
      </p>
    </template>

    <template v-else-if="job.stage === 'merged' || job.stage === 'rejected'">
      <div class="flex items-center gap-2.5">
        <span class="flex size-[30px] flex-none items-center justify-center rounded-lg border-[1.5px] border-success/40 text-success">
          <CircleCheck class="size-4" />
        </span>
        <div class="flex flex-col leading-snug">
          <b class="text-sm font-semibold">{{ job.stage === 'merged' ? 'Entregue' : 'Rejeitado' }}</b>
          <span class="text-xs text-faint">
            {{ job.stage === 'merged' ? `mesclado no PR #${job.pr}` : 'o job terminou sem mesclar' }}
          </span>
        </div>
      </div>
      <p class="mt-3 text-[13px] text-muted-foreground">
        Nada espera por você neste job. Escolha outro em <b class="font-semibold text-foreground">Destacar</b>.
      </p>
    </template>

    <template v-else>
      <div class="flex items-center gap-2.5">
        <span class="flex size-[30px] flex-none items-center justify-center rounded-lg border-[1.5px] border-primary text-agent">
          <Signpost class="size-4" />
        </span>
        <div class="flex flex-col leading-snug">
          <b class="text-sm font-semibold">Próxima parada: {{ next?.name ?? 'fim da linha' }}</b>
          <span class="text-xs text-faint">depois de {{ line.find((n) => n.id === job.node)?.name }}</span>
        </div>
      </div>
      <p class="mt-3 text-[13px] text-muted-foreground">
        Nenhuma decisão sua é necessária agora. O núcleo segue sozinho e só para se uma rodada se esgotar ou algo falhar.
      </p>
    </template>
  </Card>
</template>
