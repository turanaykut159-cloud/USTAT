/**
 * ÜSTAT v5.9 — Sürüklenebilir Kart Sarmalayıcı (@dnd-kit)
 *
 * Hibrit İşlem Paneli kartlarının sürükle-bırak ile yeniden
 * sıralanabilmesini sağlar.
 *
 * Kullanım:
 *   <SortableCard id="summary" disabled={false}>
 *     <div>Kart içeriği</div>
 *   </SortableCard>
 *
 * CSS sınıfları: .grid-card, .drag-handle (theme.css'den)
 */

import React from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

export default function SortableCard({ id, label, disabled, children }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 100 : undefined,
  };

  return (
    <div ref={setNodeRef} style={style} className="grid-card">
      {/* Sürükleme tutamağı */}
      {!disabled && (
        <div className="drag-handle" {...attributes} {...listeners}>
          ⋮⋮ {label}
        </div>
      )}
      {children}
    </div>
  );
}
