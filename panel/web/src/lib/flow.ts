import { useVueFlow } from '@vue-flow/core'
import { ref } from 'vue'

/** The id of the line's flow, shared by the graph and its controls. */
export const LINE_FLOW = 'line'

export const SPACING = 190
const NODE_W = 140
const ABOVE = 104 // room for the ways back and their labels, in flow units
const SIDES = 48
const BELOW = 150 // the node, its name, files and chip

/** The zoom that frames the whole line: the cards below scale relative to it. */
export const fitZoom = ref(1)

export function lineWidth(count: number) {
  return (count - 1) * SPACING + NODE_W
}

/** Frame the whole line, ways back included, centred in a box of this size. */
export function useLineView(count: () => number) {
  const flow = useVueFlow(LINE_FLOW)
  function fit(boxWidth: number, boxHeight: number, duration = 0) {
    const width = lineWidth(count())
    const zoom = Math.min(1, Math.max(0.4, (boxWidth - SIDES) / width))
    fitZoom.value = zoom
    flow.setViewport({ x: (boxWidth - width * zoom) / 2, y: Math.max(ABOVE * zoom + 12, (boxHeight - (ABOVE + BELOW) * zoom) / 2 + ABOVE * zoom), zoom }, { duration })
  }
  return { ...flow, fit }
}
