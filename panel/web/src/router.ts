import { createRouter, createWebHistory } from 'vue-router'
import { TABS } from '@/lib/tabs'
import HomeView from '@/views/HomeView.vue'
import PlaceholderView from '@/views/PlaceholderView.vue'
import ProjectLayout from '@/views/ProjectLayout.vue'
import StartView from '@/views/StartView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: StartView },
    {
      path: '/:project',
      component: ProjectLayout,
      children: TABS.map((tab) => ({
        path: tab.path,
        name: tab.path || 'inicio',
        component: tab.path ? PlaceholderView : HomeView,
        meta: { tab },
      })),
    },
  ],
})
