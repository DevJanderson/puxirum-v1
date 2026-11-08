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
  function toggle() {
    const dark = document.documentElement.classList.contains('dark')
    choice.value = dark ? 'light' : 'dark'
    try {
      localStorage.setItem(KEY, choice.value)
    } catch {
      /* private window: the choice lasts until the page closes */
    }
  }
  return { choice, toggle }
}
