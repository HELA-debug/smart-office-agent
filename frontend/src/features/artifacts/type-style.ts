import { IconDoc, IconFile, IconPdf, IconSheet, IconSlides, IconText } from '../../shared/ui/Icons';
import type { ComponentType } from 'react';

/**
 * 产物类型的视觉映射：图标 + 底色 + 标签配色。
 *
 * 抽成独立模块是因为有两个地方要用同一套语言：
 * 右栏「产物仓库」的一行、对话里的交付卡片。
 * 以前所有产物共用一个文件图标 + 一个蓝块，一列 DOCX / PDF / TXT 长得完全一样。
 */
export const ARTIFACT_TYPE_STYLE: Record<
  string,
  { tile: string; chip: string; icon: ComponentType<{ size?: number }> }
> = {
  docx: { tile: 'bg-brand-soft text-brand', chip: 'bg-brand-soft text-brand', icon: IconDoc },
  xlsx: { tile: 'bg-ok-soft text-ok', chip: 'bg-ok-soft text-ok', icon: IconSheet },
  pdf: { tile: 'bg-danger-soft text-danger', chip: 'bg-danger-soft text-danger', icon: IconPdf },
  pptx: { tile: 'bg-warn-soft text-warn', chip: 'bg-warn-soft text-warn', icon: IconSlides },
  txt: {
    tile: 'bg-surface-sunken text-muted',
    chip: 'bg-surface-sunken text-muted',
    icon: IconText,
  },
  md: { tile: 'bg-accent-soft text-accent', chip: 'bg-accent-soft text-accent', icon: IconText },
  csv: { tile: 'bg-ok-soft text-ok', chip: 'bg-ok-soft text-ok', icon: IconSheet },
  html: { tile: 'bg-accent-soft text-accent', chip: 'bg-accent-soft text-accent', icon: IconFile },
  upload: {
    tile: 'bg-accent-soft text-accent',
    chip: 'bg-accent-soft text-accent',
    icon: IconFile,
  },
};

export const ARTIFACT_FALLBACK_STYLE = {
  tile: 'bg-surface-sunken text-muted',
  chip: 'bg-surface-sunken text-muted',
  icon: IconFile,
};

export function artifactTypeStyle(type: string) {
  return ARTIFACT_TYPE_STYLE[type] ?? ARTIFACT_FALLBACK_STYLE;
}

/** `周报_2026-W43.docx` → `周报_2026-W43`：扩展名交给右侧的类型标签，别在名字里重复一遍。 */
export function stripExtension(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot > 0 ? filename.slice(0, dot) : filename;
}
