/**
 * 配置层单测：特性开关/导航、供应商入口、产物格式。
 *
 * 这些常量被导航、设置页、Composer 直接消费，改动会静默影响多个页面，
 * 因此用契约断言锁住（例如「占位页不能变成已实现」这类回归）。
 */
import { describe, expect, it } from 'vitest';
import {
  FEATURE_FLAGS,
  NAV_ITEMS,
  PLACEHOLDER_NAV,
  PLACEHOLDER_ROUTES,
  type FeatureKey,
} from './feature-flags';
import {
  DEFAULT_OUTPUT_FORMAT,
  MEDIA_KIND_LABELS,
  MEDIA_UPLOAD_EXTENSIONS,
  OUTPUT_FORMATS,
  OUTPUT_FORMAT_COMPACT,
  OUTPUT_FORMAT_LABELS,
  OUTPUT_FORMAT_SHORT,
  UPLOADABLE_EXTENSIONS,
  UPLOAD_ACCEPT,
  UPLOAD_FORMATS,
  defaultFormatForUploads,
  extOfFilename,
  isOutputFormat,
  maxUploadMbForFile,
  mediaKindOf,
  orderedFormats,
} from './output-formats';
import {
  DEFAULT_PROVIDER,
  PROVIDER_CONSOLES,
  hasProviderConsole,
  providerConsole,
  providerLabel,
} from './providers';

describe('FEATURE_FLAGS / NAV_ITEMS', () => {
  it('每个导航项都有对应的开关，且不存在多余开关', () => {
    const navKeys = NAV_ITEMS.map((item) => item.key).sort();
    const flagKeys = Object.keys(FEATURE_FLAGS).sort() as FeatureKey[];
    expect(navKeys).toEqual(flagKeys);
  });

  it('导航路径唯一、以 / 开头，且与 key 一一对应', () => {
    const paths = NAV_ITEMS.map((item) => item.path);
    expect(new Set(paths).size).toBe(paths.length);
    for (const item of NAV_ITEMS) {
      expect(item.path.startsWith('/')).toBe(true);
      expect(item.label.length).toBeGreaterThan(0);
      expect(item.description.length).toBeGreaterThan(0);
    }
  });

  it('real=true 的导航项，其开关必须为 true（否则入口会消失）', () => {
    for (const item of NAV_ITEMS) {
      if (item.real) expect(FEATURE_FLAGS[item.key]).toBe(true);
    }
  });

  it('占位页集合与 real=false 的项一致', () => {
    expect(PLACEHOLDER_NAV.map((item) => item.key)).toEqual(
      NAV_ITEMS.filter((item) => !item.real).map((item) => item.key),
    );
    expect(PLACEHOLDER_ROUTES).toEqual(PLACEHOLDER_NAV.map((item) => item.key));
  });

  it('当前占位页只剩知识库（回归哨兵：实现后需同步改这里）', () => {
    expect(PLACEHOLDER_ROUTES).toEqual(['knowledge']);
  });
});

describe('providerConsole', () => {
  it('已知供应商返回自身配置', () => {
    for (const [key, console] of Object.entries(PROVIDER_CONSOLES)) {
      expect(providerConsole(key)).toBe(console);
    }
  });

  it('null / undefined / 未知供应商回落到默认供应商', () => {
    const fallback = providerConsole(null);
    expect(fallback).toBe(PROVIDER_CONSOLES[DEFAULT_PROVIDER]);
    expect(providerConsole(undefined)).toBe(fallback);
    expect(providerConsole('not-a-provider')).toBe(fallback);
  });

  it('所有入口都是 https 且非空（跳转外链不允许降级为 http）', () => {
    for (const console of Object.values(PROVIDER_CONSOLES)) {
      expect(console.label.length).toBeGreaterThan(0);
      for (const url of [console.topUp, console.usage, console.keys]) {
        expect(url.startsWith('https://')).toBe(true);
      }
    }
  });
});

describe('providerLabel', () => {
  it('deepseek 在界面上叫 deepseek harness（标识仍是 deepseek）', () => {
    expect(providerLabel('deepseek')).toBe('deepseek harness');
    expect(PROVIDER_CONSOLES.deepseek?.label).toBe('deepseek harness');
  });

  it('WorkBuddy 有名字但没有开放平台入口，也不出现在「去充值」菜单里', () => {
    expect(providerLabel('workbuddy')).toBe('WorkBuddy');
    expect(hasProviderConsole('workbuddy')).toBe(false);
    // 充值菜单直接遍历这张表，所以它必须在表外
    expect(PROVIDER_CONSOLES.workbuddy).toBeUndefined();
  });

  it('没登记过的供应商原样显示，空值给占位符', () => {
    expect(providerLabel('my-own')).toBe('my-own');
    expect(providerLabel(null)).toBe('—');
    expect(providerLabel('')).toBe('—');
  });
});

describe('output-formats', () => {
  it('每个格式都有长标签与短标签', () => {
    for (const format of OUTPUT_FORMATS) {
      expect(OUTPUT_FORMAT_LABELS[format]).toBeTruthy();
      expect(OUTPUT_FORMAT_SHORT[format]).toBe(format);
    }
  });

  it('中等标签去掉后缀括号，仍能认出是哪个格式', () => {
    for (const format of OUTPUT_FORMATS) {
      const compact = OUTPUT_FORMAT_COMPACT[format];
      expect(compact).toBeTruthy();
      // 折叠行右侧位置窄，括号里的后缀交给二级面板去说
      expect(compact).not.toContain('（');
      expect(OUTPUT_FORMAT_LABELS[format].startsWith(compact)).toBe(true);
    }
  });

  it('isOutputFormat 精确识别，拒绝大写与未知值', () => {
    expect(isOutputFormat('docx')).toBe(true);
    expect(isOutputFormat('md')).toBe(false);
    expect(isOutputFormat('html')).toBe(false);
    expect(isOutputFormat('DOCX')).toBe(false);
    expect(isOutputFormat('pptx')).toBe(true);
    expect(isOutputFormat('')).toBe(false);
  });

  it('上传 accept 覆盖文档与媒体，且没有重复项', () => {
    for (const format of UPLOAD_FORMATS) {
      expect(UPLOAD_ACCEPT).toContain(`.${format}`);
    }
    // csv 能当素材传，但不能当产物
    expect(UPLOAD_ACCEPT).toContain('.csv');
    expect(isOutputFormat('csv')).toBe(false);
    // 图片 / 录音 / 视频也在 whitelist 里（文件选择与拖拽共用这一份）
    for (const exts of Object.values(MEDIA_UPLOAD_EXTENSIONS)) {
      for (const ext of exts) expect(UPLOAD_ACCEPT).toContain(ext);
    }
    // 分隔符必须干净，且去重后长度不变（重复项会让 accept 串变长、判断逻辑出错）
    const parts = UPLOAD_ACCEPT.split(',');
    expect(parts.every((part) => part.startsWith('.') && part.length > 1)).toBe(true);
    expect(new Set(parts).size).toBe(parts.length);
    expect(UPLOADABLE_EXTENSIONS).toEqual(parts);
  });

  it('媒体类别与单文件上限：图片/音视频 200MB，转写稿与文档 20MB', () => {
    expect(mediaKindOf('周会截图.PNG')).toBe('image');
    expect(mediaKindOf('会议录音.m4a')).toBe('audio');
    expect(mediaKindOf('例会.mp4')).toBe('video');
    expect(mediaKindOf('转写稿.srt')).toBe('transcript');
    expect(mediaKindOf('周报.docx')).toBeNull();
    expect(maxUploadMbForFile('会议录音.wav')).toBe(200);
    expect(maxUploadMbForFile('转写稿.vtt')).toBe(20);
    expect(maxUploadMbForFile('周报.docx')).toBe(20);
    // 界面上按 kind 取徽标文案，缺一项就会显示成空白
    for (const kind of ['image', 'transcript', 'audio', 'video'] as const) {
      expect(MEDIA_KIND_LABELS[kind]).toBeTruthy();
    }
  });

  it('extOfFilename 取小写后缀，无后缀或多点文件也正确', () => {
    expect(extOfFilename('a.docx')).toBe('docx');
    expect(extOfFilename('A.DOCX')).toBe('docx');
    expect(extOfFilename('archive.tar.gz')).toBe('gz');
    expect(extOfFilename('  b.pdf  ')).toBe('pdf');
    expect(extOfFilename('noext')).toBe('');
    expect(extOfFilename('trailing.')).toBe('');
  });

  it('defaultFormatForUploads 跟随首个可识别素材，否则回退 docx', () => {
    expect(defaultFormatForUploads([{ filename: 'x.pdf' }])).toBe('pdf');
    // md / csv 已下线：素材格式不在可选范围时统一回退 docx
    expect(defaultFormatForUploads([{ filename: 'a.pptx' }, { filename: 'b.md' }])).toBe('pptx');
    expect(defaultFormatForUploads([{ filename: 'a.csv' }, { filename: 'b.docx' }])).toBe('docx');
    expect(defaultFormatForUploads([{ filename: 'notes' }])).toBe('docx');
    expect(defaultFormatForUploads([])).toBe(DEFAULT_OUTPUT_FORMAT);
  });

  it('orderedFormats 首项=base，其余不重复且覆盖全部格式', () => {
    for (const base of OUTPUT_FORMATS) {
      const ordered = orderedFormats(base);
      expect(ordered[0]).toBe(base);
      expect(new Set(ordered).size).toBe(ordered.length);
      expect(ordered).toHaveLength(OUTPUT_FORMATS.length);
    }
  });
});
