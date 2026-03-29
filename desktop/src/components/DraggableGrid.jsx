/**
 * ÜSTAT v5.9 — DraggableGrid (DEPRECATED)
 *
 * Bu bileşen artık kullanılmıyor. react-grid-layout v2 uyumsuzluğu
 * nedeniyle @dnd-kit tabanlı SortableCard.jsx ile değiştirilmiştir.
 *
 * Bu dosya geriye dönük uyumluluk için korunmaktadır.
 * Yeni kullanım: SortableCard.jsx + DndContext + SortableContext
 */

export default function DraggableGrid({ children }) {
  console.warn('DraggableGrid DEPRECATED — SortableCard.jsx kullanın');
  return <div>{children}</div>;
}
