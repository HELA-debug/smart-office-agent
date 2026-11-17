import type { SVGProps } from 'react';

export interface IconProps extends SVGProps<SVGSVGElement> {
  size?: number;
}

function base({ size = 16, ...props }: IconProps): SVGProps<SVGSVGElement> {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': true,
    ...props,
  };
}

/**
 * 品牌标识：与桌面端应用图标同一个符号（白底深墨的文档 + 蓝色星）。
 *
 * 这里用 512 的 viewBox 直接缩放，好处是跟 `public/icons/icon.svg` 永远同源。
 * 两个必须的差异：
 *   - 顶栏只显示 21px，省掉第三条文字行、剩下两条加粗，否则会糊成一片灰；
 *   - 白底落在白色顶栏上会「消失」，所以补一圈描边。
 */
export function IconLogo({ size = 20, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" fill="none" aria-hidden {...props}>
      <rect width="512" height="512" rx="112" fill="#ffffff" />
      <rect
        x="6"
        y="6"
        width="500"
        height="500"
        rx="106"
        fill="none"
        stroke="#cbd5e1"
        strokeWidth="12"
      />
      <path
        d="M186 96H280L356 172V386A30 30 0 0 1 326 416H186A30 30 0 0 1 156 386V126A30 30 0 0 1 186 96Z"
        fill="#0d1526"
      />
      <path d="M280 96L356 172H288A8 8 0 0 1 280 164Z" fill="#eef2f7" />
      <rect x="194" y="250" width="124" height="30" rx="15" fill="#ffffff" />
      <rect x="194" y="318" width="82" height="30" rx="15" fill="#ffffff" />
      <path
        d="M398 282C404 334 412 342 466 348C412 354 404 362 398 414C392 362 384 354 330 348C384 342 392 334 398 282Z"
        fill="#2563eb"
      />
    </svg>
  );
}

export function IconPlus(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

/** 钥匙（Key 管理入口）。 */
export function IconKey(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="8" cy="15" r="4" />
      <path d="M10.8 12.2 20 3M17 6l2.5 2.5M14.5 8.5 17 11" />
    </svg>
  );
}

/** 眼睛（预览入口）。 */
export function IconEye(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M2.5 12S5.8 5.5 12 5.5 21.5 12 21.5 12 18.2 18.5 12 18.5 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

/** 竖向三点（更多操作菜单入口）。 */
export function IconDots(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="5" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="12" cy="19" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** 拖拽手柄（两列六点）：卡片可拖动排序时的抓手。 */
export function IconGrip(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="9" cy="6" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="15" cy="6" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="9" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="15" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="9" cy="18" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="15" cy="18" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** 分享（向上箭头出框）：把会话/产物发给别人。 */
export function IconShare(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 15.5V4.2" />
      <path d="M8.2 7.6 12 3.8l3.8 3.8" />
      <path d="M5.5 13.4v4.4a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-4.4" />
    </svg>
  );
}

/** 链接（两节链条）：复制链接类动作。 */
export function IconLink(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M9.2 14.8 14.8 9.2" />
      <path d="M11 7.4 12.6 5.8a3.6 3.6 0 1 1 5.1 5.1L16.1 12.5" />
      <path d="M13 16.6l-1.6 1.6a3.6 3.6 0 1 1-5.1-5.1l1.6-1.6" />
    </svg>
  );
}

/** 桌面端（显示器）：装到本机直接读写文件夹。 */
export function IconMonitor(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="4.5" width="18" height="12" rx="2" />
      <path d="M9 20h6" />
      <path d="M12 16.5V20" />
    </svg>
  );
}

/** 用量仪表（环形 + 指针）。 */
export function IconGauge(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4.5 17a8.5 8.5 0 1 1 15 0" />
      <path d="M12 13.5l3.2-3.6" />
      <circle cx="12" cy="13.8" r="1.2" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** 模型/技能（四角星）。 */
export function IconSparkle(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" />
      <path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z" />
    </svg>
  );
}

export function IconSend(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4.5 11.5 20 4l-7.5 15.5-2.2-6.3-5.8-1.7Z" />
    </svg>
  );
}

export function IconStop(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="6.5" y="6.5" width="11" height="11" rx="2" />
    </svg>
  );
}

export function IconPaperclip(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M20 11.5 12.2 19.3a4.7 4.7 0 0 1-6.6-6.6l7.8-7.8a3.1 3.1 0 0 1 4.4 4.4l-7.8 7.8a1.6 1.6 0 0 1-2.2-2.2l7.1-7.1" />
    </svg>
  );
}

export function IconChevronDown(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

export function IconChevronRight(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

export function IconChevronUp(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="m6 15 6-6 6 6" />
    </svg>
  );
}

export function IconCheck(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="m5 12.5 4.5 4.5L19 7" />
    </svg>
  );
}

export function IconCheckCircle(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="m8.2 12.3 2.4 2.4 5.2-5.2" />
    </svg>
  );
}

export function IconCircle(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="8" />
    </svg>
  );
}

export function IconSpinner({ size = 16, ...props }: IconProps) {
  return (
    <svg
      {...base({ size, ...props })}
      className={`animate-spin ${props.className ?? ''}`}
      style={props.style}
    >
      <path d="M12 3a9 9 0 1 0 9 9" />
    </svg>
  );
}

export function IconAlertTriangle(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M10.3 3.9 2.9 17a2 2 0 0 0 1.7 3h14.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
      <path d="M12 9v4.2M12 16.6h.01" />
    </svg>
  );
}

export function IconInfo(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </svg>
  );
}

export function IconX(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

export function IconFile(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5M9 13h6M9 17h4" />
    </svg>
  );
}

/** Word/文档：带折角的纸 + 两行正文（跟「未知文件」的空纸区分开）。 */
export function IconDoc(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5" />
      <path d="M8.5 12.5h7M8.5 16h5" strokeWidth={2} />
    </svg>
  );
}

/** 表格：纸 + 网格（Excel / CSV）。 */
export function IconSheet(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5M8.5 12h7M8.5 12v6.5M12 12v6.5M15.5 12v6.5M8.5 15.2h7M8.5 18.5h7" />
    </svg>
  );
}

/** PDF：纸 + 一个「P」字花体，比纯色块更容易一眼认出。 */
export function IconPdf(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5" />
      <path d="M9.6 17.5v-5.2h1.7a1.6 1.6 0 0 1 0 3.2H9.6" strokeWidth={2} />
    </svg>
  );
}

/** 纯文本：纸 + 更密的行。 */
export function IconText(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5M8.5 12h7M8.5 15h7M8.5 18h4" />
    </svg>
  );
}

/** 演示文稿：投影幕 + 底座（PPT）。别用纸的形状——PPT 不是一张纸。 */
export function IconSlides(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M12 16v3M8.5 21h7" />
    </svg>
  );
}

export function IconMail(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="5" width="18" height="14" rx="2.5" />
      <path d="m3.8 7 8.2 6 8.2-6" />
    </svg>
  );
}

/** 复制：两张叠起来的纸（后一张只留折角，20px 下也不会糊成一团）。 */
export function IconCopy(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="9" y="9" width="11" height="11" rx="2.2" />
      <path d="M6.5 15H5.6A1.6 1.6 0 0 1 4 13.4V5.6A1.6 1.6 0 0 1 5.6 4h7.8A1.6 1.6 0 0 1 15 5.6v.9" />
    </svg>
  );
}

export function IconShield(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 3 5 5.7v5.6c0 4.3 2.9 7.6 7 9.7 4.1-2.1 7-5.4 7-9.7V5.7L12 3Z" />
      <path d="m9 12 2.2 2.2L15.4 10" />
    </svg>
  );
}

export function IconBot(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="4" y="8" width="16" height="11" rx="3" />
      <path d="M12 4v4M8.5 13h.01M15.5 13h.01M9.5 16h5" />
    </svg>
  );
}

export function IconTerminal(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="4.5" width="18" height="15" rx="2.5" />
      <path d="m7.5 9.5 2.8 2.5-2.8 2.5M12.5 15h4" />
    </svg>
  );
}

export function IconList(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" />
    </svg>
  );
}

export function IconClock(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5V12l3 1.8" />
    </svg>
  );
}

export function IconDownload(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14" />
    </svg>
  );
}

export function IconExternal(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M14 4h6v6M20 4l-8.5 8.5" />
      <path d="M18 14.5V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3.5" />
    </svg>
  );
}

export function IconSettings(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
    </svg>
  );
}

export function IconBook(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15.5H6.5A2.5 2.5 0 0 0 4 21V5.5Z" />
      <path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20" />
    </svg>
  );
}

/** 插件（拼图）：扩展页「插件」tab 的图标。 */
export function IconPuzzle(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M10 4.5a2 2 0 0 1 4 0V6h3.5A1.5 1.5 0 0 1 19 7.5V11h-1.5a2 2 0 0 0 0 4H19v3.5a1.5 1.5 0 0 1-1.5 1.5H14v-1.5a2 2 0 0 0-4 0V20H6.5A1.5 1.5 0 0 1 5 18.5V15h1.5a2 2 0 0 0 0-4H5V7.5A1.5 1.5 0 0 1 6.5 6H10V4.5Z" />
    </svg>
  );
}

/** 电源：技能卡片上的「启用 / 停用」。 */
export function IconPower(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 3.5v8" />
      <path d="M7.2 6.6a7 7 0 1 0 9.6 0" />
    </svg>
  );
}

export function IconInbox(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 13.5 6.2 5a2 2 0 0 1 1.9-1.5h7.8A2 2 0 0 1 17.8 5L20 13.5V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-4.5Z" />
      <path d="M4 13.5h4.2l1.3 2h5l1.3-2H20" />
    </svg>
  );
}

export function IconPanelRight(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="4.5" width="18" height="15" rx="2.5" />
      <path d="M15 4.5v15" />
    </svg>
  );
}

export function IconRefresh(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M20 12a8 8 0 1 1-2.4-5.7" />
      <path d="M20 4v4.5h-4.5" />
    </svg>
  );
}

/** 展开到全窗口：四角朝外。和 IconMinimize 成对使用（同一个位置来回切）。 */
export function IconExpand(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M9 4H4v5M15 4h5v5M15 20h5v-5M9 20H4v-5" />
    </svg>
  );
}

/** 还原成半窗口：四角朝内。 */
export function IconCollapse(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 9h5V4M20 9h-5V4M20 15h-5v5M4 15h5v5" />
    </svg>
  );
}

export function IconWand(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="m5 19 9-9M14 5l1.2 2.8L18 9l-2.8 1.2L14 13l-1.2-2.8L10 9l2.8-1.2L14 5ZM19 15l.7 1.6L21.3 17l-1.6.7L19 19.3l-.7-1.6L16.7 17l1.6-.7L19 15Z" />
    </svg>
  );
}

export function IconSearch(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </svg>
  );
}

export function IconFolder(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3.5 7.5A2 2 0 0 1 5.5 5.5H9l2 2.5h7.5a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-9.5Z" />
    </svg>
  );
}

export function IconArrowRight(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M5 12h14M13.5 6.5 19 12l-5.5 5.5" />
    </svg>
  );
}

export function IconPin(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M9 4h6l-1 6 3.5 3.5H6.5L10 10 9 4Z" />
      <path d="M12 13.5V21" />
    </svg>
  );
}

export function IconTrash(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13" />
      <path d="M10 11v5M14 11v5" />
    </svg>
  );
}

export function IconPencil(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="m4.5 19.5 4.2-1 10-10a2.1 2.1 0 0 0-3-3l-10 10-1.2 4Z" />
      <path d="m13.5 7.5 3 3" />
    </svg>
  );
}

export function IconPlay(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M8 5.5v13l11-6.5-11-6.5Z" />
    </svg>
  );
}

export function IconPause(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M9 5.5v13M15 5.5v13" />
    </svg>
  );
}

export function IconRotate(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 12a8 8 0 1 0 2.4-5.7" />
      <path d="M4 4v4.5h4.5" />
    </svg>
  );
}

export function IconFilter(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 5h16l-6.2 7.3V19l-3.6 1.5v-8.2L4 5Z" />
    </svg>
  );
}

export function IconExport(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 15V4M8 8l4-4 4 4" />
      <path d="M5 14v4.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V14" />
    </svg>
  );
}

export function IconChevronLeft(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="m15 6-6 6 6 6" />
    </svg>
  );
}

export function IconSun(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2M12 19.5v2M4.5 4.5l1.4 1.4M18.1 18.1l1.4 1.4M2.5 12h2M19.5 12h2M4.5 19.5l1.4-1.4M18.1 5.9l1.4-1.4" />
    </svg>
  );
}

export function IconMoon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a7 7 0 1 0 10.5 10.5Z" />
    </svg>
  );
}

/* 比赛版新增：语音输入 / 朗读输出 / 多方案选择（统一 24 viewBox、1.8 描边、对读屏隐藏） */

export function IconMic(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 15.5a3.5 3.5 0 0 0 3.5-3.5V6.5a3.5 3.5 0 1 0-7 0v5.5a3.5 3.5 0 0 0 3.5 3.5Z" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18.5V21" />
    </svg>
  );
}

export function IconVolume(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M11 5 6.5 9H3.5v6h3L11 19V5Z" />
      <path d="M15 9.5a3.5 3.5 0 0 1 0 5M17.8 7a7 7 0 0 1 0 10" />
    </svg>
  );
}

export function IconOptions(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3.5" y="4" width="7" height="16" rx="2" />
      <rect x="14" y="4" width="6.5" height="6.5" rx="2" />
      <rect x="14" y="13.5" width="6.5" height="6.5" rx="2" />
    </svg>
  );
}

export function IconPanelLeft(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="4.5" width="18" height="15" rx="2.5" />
      <path d="M9 4.5v15" />
    </svg>
  );
}

/** 发送/提交：圆形按钮里的上箭头。 */
export function IconArrowUp(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 19.5V5M6 11l6-6 6 6" />
    </svg>
  );
}
