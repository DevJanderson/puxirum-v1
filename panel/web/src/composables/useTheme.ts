import { ref, watchEffect } from 'vue'

type Choice = 'light' | 'dark' | 'system'
const KEY = 'puxirum-theme'

function saved(): Choice {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

const choice = ref<Choice>(saved())
const media = window.matchMedia('(prefers-color-scheme: dark)')
const systemDark = ref(media.matches)
media.addEventListener('change', (e) => (systemDark.value = e.matches))

watchEffect(() => {
  const dark = choice.value === 'dark' || (choice.value === 'system' && systemDark.value)
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
})

/** Light, dark or the system's, remembered in this browser. */
export function useTheme() {
  function set(next: Choice) {
    choice.value = next
    try {
      if (next === 'system') localStorage.removeItem(KEY)
      else localStorage.setItem(KEY, next)
    } catch {
      /* private window: the choice lasts until the page closes */
    }
  }
  function toggle() {
    set(document.documentElement.classList.contains('dark') ? 'light' : 'dark')
  }
  return { choice, set, toggle }
}
