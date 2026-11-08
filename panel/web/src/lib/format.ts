export const STAGE_NAMES: Record<string, string> = {
  intake: 'intake',
  'needs-info': 'aguarda o autor',
  spec: 'spec',
  build: 'build',
  gate: 'gate',
  review: 'revisão',
  approve: 'aprovação',
  merging: 'merge',
  'needs-human': 'aguarda você',
  merged: 'mesclado',
  rejected: 'rejeitado',
}

export const LENS_NAMES: Record<string, string> = {
  code: 'Código',
  ux: 'UX',
  ui: 'UI',
  security: 'Segurança',
}

export function money(usd: number): string {
  return `US$ ${usd.toFixed(2)}`
}

export function duration(seconds: number): string {
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m${String(s % 60).padStart(2, '0')}s`
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}m`
}

export function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`
}
