import type { Component } from 'vue'
import {
  Boxes, ChartColumn, Database, FileText, House, ListTodo, Route, Shield, Waypoints, Workflow,
} from 'lucide-vue-next'

export interface Tab {
  path: string
  name: string
  icon: Component
  group: 'visao' | 'fabrica' | 'produto' | 'melhoria'
  question: string
  shows: string
  reads: string
}

// Every tab of the panel. Only Início has content yet; the others say what they will answer.
export const TABS: Tab[] = [
  {
    path: '', name: 'Início', icon: House, group: 'visao',
    question: 'O que está esperando por mim?',
    shows: 'A linha com cada job, os agentes trabalhando agora e o que espera por você.',
    reads: '.puxirum/state/',
  },
  {
    path: 'projeto', name: 'Projeto', icon: FileText, group: 'visao',
    question: 'O que é este projeto, numa folha?',
    shows: 'Por quê, o quê, quem, como e quanto, com a origem de cada bloco.',
    reads: 'README, AGENTS.md e .puxirum/config.toml',
  },
  {
    path: 'fila', name: 'Fila', icon: ListTodo, group: 'fabrica',
    question: 'O que está na fila e o que ficou para depois?',
    shows: 'As issues com a label da fila, o que espera e o que foi rejeitado, com busca e filtro.',
    reads: 'as issues no GitHub e .puxirum/state/',
  },
  {
    path: 'jornada', name: 'Jornada', icon: Route, group: 'produto',
    question: 'O que cada pessoa faz no produto, e em que ordem?',
    shows: 'O mapa de jornada por perfil e o fluxo de telas de cada jornada.',
    reads: 'as histórias de usuário do projeto',
  },
  {
    path: 'arquitetura', name: 'Arquitetura', icon: Boxes, group: 'produto',
    question: 'Do que o sistema é feito e quem fala com quem?',
    shows: 'Os serviços em camadas e as ligações entre eles.',
    reads: 'o documento de arquitetura e os manifestos do projeto',
  },
  {
    path: 'rotas', name: 'Rotas', icon: Waypoints, group: 'produto',
    question: 'Que telas e rotas existem?',
    shows: 'As telas com a guarda de acesso e as rotas da API por área.',
    reads: 'o código do projeto',
  },
  {
    path: 'banco', name: 'Banco de dados', icon: Database, group: 'produto',
    question: 'Como os dados estão guardados?',
    shows: 'As tabelas por área, com as chaves e as ligações entre elas.',
    reads: 'o esquema do banco do projeto',
  },
  {
    path: 'uml', name: 'UML', icon: Workflow, group: 'produto',
    question: 'Como cada entidade muda de estado?',
    shows: 'A máquina de estados de cada entidade e a tabela das transições.',
    reads: 'os diagramas do projeto',
  },
  {
    path: 'seguranca', name: 'Segurança', icon: Shield, group: 'produto',
    question: 'Onde o sistema está mais e menos protegido?',
    shows: 'Os achados das revisões de segurança e os riscos aceitos, por área.',
    reads: 'as revisões de segurança dos jobs',
  },
  {
    path: 'medicao', name: 'Medição', icon: ChartColumn, group: 'melhoria',
    question: 'A fábrica está melhorando?',
    shows: 'Custo por entrega, tempo ativo, voltas por tipo e custo por papel e por modelo.',
    reads: '.puxirum/state/runs/ e os eventos dos jobs',
  },
]
