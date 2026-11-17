import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { readApprovalMode, writeApprovalMode } from '../../shared/config/approval-modes';
import { compactDocStyle } from '../../shared/config/doc-style';
import { FEATURE_FLAGS } from '../../shared/config/feature-flags';
import {
  UPLOAD_ACCEPT,
  UPLOAD_FORMATS,
  defaultFormatForUploads,
} from '../../shared/config/output-formats';
import { isMockMode } from '../../shared/config/runtime';
import { errorMessage } from '../../shared/lib/api';
import { fetchRemoteFile } from '../../shared/lib/download';
import { MAX_UPLOAD_BYTES, artifactsApi } from '../artifacts';
import { AuditDrawer } from '../audit';
import { ProjectsSection, useProjects } from '../projects';
import { SessionList } from '../sessions';
import { SkillImportGuide, SkillsPanel, useSkills } from '../skills';
import { ApprovalPanel } from './components/ApprovalPanel';
import { BackgroundTasksBar } from './components/BackgroundTasksBar';
import { ChatStream } from './components/ChatStream';
import { Composer } from './components/Composer';
import { EmptyState } from './components/EmptyState';
import { RightPanel } from './components/RightPanel';
import { RunSummaryCard } from './components/RunSummaryCard';
import { StatusBar } from './components/StatusBar';
import { useWorkbench } from './state/useWorkbench';
import type { ApprovalMode } from '../../shared/config/approval-modes';
import type { DocStyle } from '../../shared/config/doc-style';
import type { OutputFormat } from '../../shared/config/output-formats';
import type { ProjectSummary } from '../projects';
import type { ArtifactItem } from './state/workbench';
import type { ChangeEvent } from 'react';

/** 项目页通过路由 state 带过来的「带着这些文件开始」。 */
interface ProjectStartState {
  projectId?: string;
  projectName?: string;
  projectFiles?: string[];
}

/** 可以放回对话框的产物格式：与后端素材上传支持的类型保持一致（上传会拒收其它格式）。 */
// 能放回对话框的格式 = 能上传的格式：两边都从 shared/config 的格式表来，别各写一份
const ADDABLE_TO_CHAT_EXTS = new Set<string>(UPLOAD_FORMATS);
const ADDABLE_TO_CHAT_HINT = UPLOAD_FORMATS.join(' / ');

export function WorkbenchPage() {
  const controller = useWorkbench();
  const { state } = controller;
  const navigate = useNavigate();
  const location = useLocation();
  const projects = useProjects();
  const skills = useSkills();
  const [approvalMode, setApprovalMode] = useState<ApprovalMode>(() => readApprovalMode());
  // 本次任务关联的项目：左栏点选，或项目页「用这些文件开始」
  const [activeProject, setActiveProject] = useState<ProjectSummary | null>(null);
  const [projectFiles, setProjectFiles] = useState<string[] | null>(null);
  const [draft, setDraft] = useState('');
  // 待确认卡片的位置：输入区那条「去确认」要能把它滚进视野
  const approvalRef = useRef<HTMLDivElement>(null);
  // 右栏默认收起：交付物已经摆在对话里，仓库是「回头翻」时才展开的次要视图
  const [rightOpen, setRightOpen] = useState(false);
  // 左栏与右栏各自独立收起：左栏收成图标条（桌面端惯例），右栏整体隐藏
  const [leftOpen, setLeftOpen] = useState(() => {
    if (typeof window === 'undefined') return true;
    return window.localStorage.getItem('oa.leftRail') !== 'collapsed';
  });
  // 导入技能的引导：输入框的技能弹层和技能页共用同一个（说明 + 下载模板 + 选文件）
  const [importGuideOpen, setImportGuideOpen] = useState(false);
  // 断位跟踪：桌面渲染常驻侧栏，移动端渲染抽屉；两者只挂载一份，避免重复控件
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window === 'undefined' || window.matchMedia('(min-width: 1024px)').matches,
  );
  // 产物格式：未手动改选时始终跟随首个上传素材；用户改选后以用户为准
  const [outputFormat, setOutputFormat] = useState<OutputFormat>(() =>
    defaultFormatForUploads(state.uploads),
  );
  const [formatTouched, setFormatTouched] = useState(false);
  /**
   * 文档格式：加号菜单里点过的字体 / 字号 / 字型 / 行距 / 缩进 / 对齐。
   *
   * 空对象表示「这一轮不干预」——交给 Agent 按文档类型自己定，
   * 这也正是用户说的「也可以由你去判断」。所以不做默认值填充。
   */
  const [docStyle, setDocStyle] = useState<DocStyle>({});
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (formatTouched) return;
    setOutputFormat(defaultFormatForUploads(state.uploads));
  }, [state.uploads, formatTouched]);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const query = window.matchMedia('(min-width: 1024px)');
    const onChange = () => setIsDesktop(query.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  // 收起状态写进 localStorage：刷新后保持用户上次的选择
  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem('oa.leftRail', leftOpen ? 'expanded' : 'collapsed');
  }, [leftOpen]);

  // 桌面端图标的「新建会话」快捷方式：/?new=1 进来直接开一张空白会话，再把参数抹掉
  const newThreadShortcut = controller.newThread;
  useEffect(() => {
    if (new URLSearchParams(location.search).get('new') !== '1') return;
    newThreadShortcut();
    navigate('/', { replace: true });
  }, [location.search, newThreadShortcut, navigate]);

  const isMock = isMockMode();
  /** 实际在跑的引擎是不是演示：健康检查的 mode 优先，拿不到时退回地址里的 mock=1。
   *  「素材会不会发出去」这类文案统一用它，别再各判各的。 */
  const engineMock = (state.health.mode ?? (isMock ? 'mock' : 'real')) === 'mock';
  /**
   * 发送门禁：真实引擎下一个能用的模型都没有（一家 Key 都没配）。
   * 此时发送按钮拦住消息并引导去配模型；已配好模型则不拦——Agent 自动用
   * 当前那家，不用每开一个会话都手动挑一遍。健康检查拿不到时不拦
   * （后端还有一道同口径的兜底校验，真发不出去会收到明确报错）。
   */
  const modelBlocked = state.health.status === 'ok' && state.health.modelReady === false;

  const startFromProject = useCallback(
    (payload: ProjectStartState) => {
      if (!payload.projectId) return;
      const name = payload.projectName || '项目';
      setActiveProject({
        id: payload.projectId,
        name,
        path: '',
        created_at: '',
        pinned: false,
        file_count: payload.projectFiles?.length ?? 0,
        missing: false,
      });
      setProjectFiles(payload.projectFiles?.length ? payload.projectFiles : null);
      if (payload.projectFiles?.length) {
        const names = payload.projectFiles.map((item) => item.split('/').pop() ?? item);
        setDraft(`请阅读项目「${name}」里的这几个文件：${names.join('、')}，然后`);
      }
      // 清掉路由 state，刷新后不会重复带入
      navigate('/', { replace: true, state: null });
    },
    [navigate],
  );

  useEffect(() => {
    const payload = location.state as ProjectStartState | null;
    if (payload?.projectId) startFromProject(payload);
  }, [location.state, startFromProject]);

  const submit = () => {
    const text = draft;
    if (!text.trim()) return;
    setDraft('');
    void controller.sendMessage(
      text,
      outputFormat,
      activeProject ? { id: activeProject.id, files: projectFiles ?? undefined } : null,
      approvalMode,
      compactDocStyle(docStyle),
    );
  };

  const onUploadInput = (event: ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (files && files.length > 0) {
      void controller.uploadFiles(Array.from(files));
    }
    event.target.value = '';
  };

  const canAudit = state.threadId !== null && (state.usage !== null || state.artifacts.length > 0);

  /**
   * 「添加到对话框」：把一份产物放回输入框，作为下一轮的素材。
   *
   * 走的是和用户手动选文件完全相同的一条路（取回文件 → 走素材上传 → 出现在输入框的
   * 素材条里），而不是在消息里塞一个「见附件」的字符串：生成物与上传物在后端是两类资源，
   * 只有真的进了「本次素材」，下一轮的工具才读得到它的正文。
   */
  const addArtifactToChat = useCallback(
    async (artifact: ArtifactItem) => {
      const ext = (artifact.filename.split('.').pop() ?? '').toLowerCase();
      if (!ADDABLE_TO_CHAT_EXTS.has(ext)) {
        controller.notify(
          'info',
          `《${artifact.filename}》的格式还不能放回对话框（支持 ${ADDABLE_TO_CHAT_HINT}）`,
        );
        return false;
      }
      if (artifact.size > MAX_UPLOAD_BYTES) {
        controller.notify('info', `《${artifact.filename}》超过上传上限，不能放回对话框`);
        return false;
      }
      try {
        const blob = await fetchRemoteFile(artifactsApi.artifactDownloadUrl(artifact.artifact_id));
        const file = new File([blob], artifact.filename, {
          type: blob.type || 'application/octet-stream',
        });
        await controller.uploadFiles([file]);
        controller.notify('info', `已把《${artifact.filename}》放回对话框，接着说想怎么改`);
        textareaRef.current?.focus();
        return true;
      } catch (error) {
        controller.notify('error', `放回对话框失败：${errorMessage(error)}`);
        return false;
      }
    },
    [controller],
  );

  // 队列按会话分：别的会话里排着的任务，不该出现在这个会话的输入框上方
  const queuedHere = state.queue.filter((item) => item.threadId === state.threadId);

  /** 审计入口始终可点：没有可审计的运行时不静默失败，而是给一条明确提示。 */
  const openAudit = () => {
    if (!canAudit) {
      controller.notify('info', '当前还没有可审计的运行：先选择一个会话，或先发起一次任务。');
      return;
    }
    void controller.openAudit();
  };

  const rightPanel = (
    <RightPanel
      artifacts={state.artifacts}
      canAudit={canAudit}
      onOpenAudit={openAudit}
      onOpenAllArtifacts={() => {
        // 带上当前会话：产物页按 `?thread=` 直接落在本会话的分类上。
        // 这个入口回答的是「我刚做的东西都去哪了」，把十几个会话的产物摊在一屏里，
        // 用户还得自己再筛一次。跨会话浏览走左栏「产物中心」（不带参数）。
        navigate(
          state.threadId ? `/artifacts?thread=${encodeURIComponent(state.threadId)}` : '/artifacts',
        );
      }}
      onAddArtifact={addArtifactToChat}
    />
  );

  return (
    /* 卡片式外壳：画布上三块独立圆角面板（左栏 / 对话区 / 右栏），
       之间靠 10px 间隙 + 细边 + 淡投影分段，不再用一条竖线把窗口切开。
       面板内部还是原来的结构，圆角裁切由各自的 overflow-hidden 负责。
       独立窗口里：窗口按钮浮在右上角，面板不再整体往下挪（上一版在这里加
       标题栏高度 + 10px，标题栏下面就空出一条，左栏顶部像悬在半空），改成
       四边一样的 10px，把按钮那一条交给各面板内部的 `.window-inset-top`。 */
    <div
      data-testid="workbench-shell"
      className="flex h-dvh gap-2.5 overflow-hidden bg-shell p-2.5 text-ink"
    >
      <div
        className="hidden shrink-0 overflow-hidden transition-[width] duration-200 ease-out md:flex"
        style={{ width: leftOpen ? 'var(--spacing-rail)' : '3.25rem' }}
      >
        <SessionList
          sessions={state.sessions}
          sessionsStatus={state.sessionsStatus}
          sessionsError={state.sessionsError}
          activeThreadId={state.threadId}
          total={state.sessionsMeta.total}
          page={state.sessionsMeta.page}
          pageSize={state.sessionsMeta.pageSize}
          collapsed={!leftOpen}
          onToggleCollapsed={() => setLeftOpen((value) => !value)}
          onNew={controller.newThread}
          onSelect={(threadId) => void controller.selectThread(threadId)}
          onRetry={() => void controller.loadSessions()}
          onRename={(threadId, title) => void controller.renameThread(threadId, title)}
          onTogglePin={(threadId, pinned) => void controller.toggleThreadPin(threadId, pinned)}
          onDelete={(threadId) => void controller.deleteThread(threadId)}
          onBulkDelete={controller.cleanupThreads}
          onLoadAllIds={controller.listAllThreadIds}
          onReorder={(threadIds) => void controller.reorderThreads(threadIds)}
          onPage={(page) => controller.goToSessionsPage(page)}
          projectsSlot={
            <ProjectsSection
              projects={projects.items}
              status={projects.status}
              error={projects.error}
              activeId={activeProject?.id ?? null}
              onSelect={(project) => {
                setActiveProject(project);
                setProjectFiles(null);
              }}
              onOpenPage={(project) => navigate(`/projects/${project.id}`)}
              onAdd={projects.add}
              onRemove={projects.remove}
              onRename={projects.rename}
              onReveal={projects.reveal}
              onNotice={controller.notify}
            />
          }
        />
      </div>

      <main className="window-inset-top flex min-w-0 flex-1 flex-col overflow-hidden rounded-panel border border-line bg-surface shadow-panel">
        <StatusBar
          health={state.health}
          mode={state.mode}
          isMockMode={isMock}
          degraded={state.degraded}
          degradedReason={state.degradedReason}
          connection={state.connection}
          runError={state.runError}
          notice={state.notice}
          onRetryRun={() => controller.retryRun(outputFormat, compactDocStyle(docStyle))}
          onRetryHealth={() => void controller.checkHealth()}
          onDismissNotice={controller.dismissNotice}
          rightOpen={rightOpen}
          onToggleRightPanel={() => setRightOpen((value) => !value)}
          leftOpen={leftOpen}
          onToggleLeftPanel={() => setLeftOpen((value) => !value)}
        />
        <ChatStream
          items={state.timeline}
          status={state.status}
          artifacts={state.artifacts}
          currentRunId={state.runId}
          onAddArtifact={addArtifactToChat}
          emptyState={
            <EmptyState mock={engineMock} onUploadRequest={() => uploadInputRef.current?.click()} />
          }
        />

        {state.usage ? (
          <div className="mx-auto w-full max-w-[54.5rem] shrink-0 px-gutter pt-1">
            <RunSummaryCard
              usage={state.usage}
              artifactCount={state.artifacts.length}
              model={state.model}
              auditEnabled={FEATURE_FLAGS.audit}
              onOpenAudit={openAudit}
            />
          </div>
        ) : null}

        {/* 待确认的操作：Agent 停在这儿等一句话。放在输入区正上方——
            用户刚看完「需要你确认」，手就在下面，不用回头翻消息。 */}
        <div className="mx-auto w-full max-w-[54.5rem] shrink-0 px-gutter">
          <ApprovalPanel
            approvals={state.approvals}
            panelRef={approvalRef}
            onSubmit={(approvalId, decision) =>
              void controller.submitApproval(approvalId, decision)
            }
          />
        </div>

        {/* 后台任务指示条：切走会话后任务继续跑，这里能看到进度并随时回去 */}
        <div className="mx-auto w-full max-w-[54.5rem] shrink-0 px-gutter">
          <BackgroundTasksBar
            onOpenThread={(threadId) => void controller.selectThread(threadId)}
            onStopTask={controller.stopBackgroundTask}
          />
        </div>

        <Composer
          value={draft}
          onChange={setDraft}
          onSubmit={submit}
          onStop={controller.stopRun}
          onUploadFiles={(files) => void controller.uploadFiles(files)}
          uploads={state.uploads}
          onRemoveUpload={controller.removeUpload}
          onRetryUpload={controller.retryUpload}
          isStreaming={controller.isStreaming}
          waitingApproval={state.status === 'waiting_approval'}
          onOpenApproval={() => approvalRef.current?.scrollIntoView({ block: 'center' })}
          outputFormat={outputFormat}
          onOutputFormatChange={(format) => {
            setFormatTouched(true);
            setOutputFormat(format);
          }}
          model={modelBlocked ? null : state.model}
          isMock={engineMock}
          modelBlocked={modelBlocked}
          modelHint={state.health.modelHint}
          onModelChanged={() => void controller.checkHealth()}
          textareaRef={textareaRef}
          project={activeProject}
          onClearProject={() => {
            setActiveProject(null);
            setProjectFiles(null);
          }}
          approvalMode={approvalMode}
          docStyle={docStyle}
          onDocStyleChange={setDocStyle}
          onApprovalModeChange={(mode) => {
            setApprovalMode(mode);
            writeApprovalMode(mode);
          }}
          skillsPanel={
            <SkillsPanel
              items={skills.items}
              status={skills.status}
              promptChars={skills.promptChars}
              busyName={skills.busyName}
              notice={skills.notice}
              onToggle={(name, enabled) => void skills.toggle(name, enabled)}
              onRemove={(name) => void skills.remove(name)}
              onImportGuide={() => setImportGuideOpen(true)}
            />
          }
          skillsSummary={
            skills.status === 'ready' && skills.items.length > 0
              ? `${skills.items.filter((item) => item.enabled).length}/${skills.items.length} 启用`
              : undefined
          }
          queue={queuedHere}
          queuePaused={state.queuePaused}
          onEditQueued={(id) => {
            const text = controller.editQueued(id);
            if (text === null) return;
            setDraft(text);
            textareaRef.current?.focus();
          }}
          onRemoveQueued={(id) => void controller.removeQueued(id)}
          onPromoteQueued={controller.promoteQueued}
          onResumeQueue={controller.resumeQueue}
        />
      </main>

      {rightOpen && isDesktop ? (
        <aside className="window-inset-top hidden w-panel shrink-0 flex-col overflow-hidden rounded-panel border border-line bg-surface shadow-panel lg:flex">
          {rightPanel}
        </aside>
      ) : null}

      {/* <1024px：右栏转抽屉（与桌面侧栏只挂载一份）。
          抽屉是 fixed inset-0，坐标相对窗口而不是外壳，所以必须自己让出标题栏高度，
          否则面板顶边和「本次会话」那一行会钻到 — □ ✕ 底下（桌面端实测到的 bug）。 */}
      {rightOpen && !isDesktop ? (
        <div
          className="fixed inset-0 z-40 flex justify-end p-2 lg:hidden"
          style={{ paddingTop: 'calc(var(--titlebar-h, 0px) + 0.5rem)' }}
        >
          <button
            type="button"
            aria-label="关闭右栏"
            className="absolute inset-0 cursor-default bg-[#101828]/35 backdrop-blur-[1px]"
            onClick={() => setRightOpen(false)}
          />
          <div className="relative flex h-full w-panel max-w-[92vw] flex-col overflow-hidden rounded-panel border border-line bg-surface shadow-pop">
            {rightPanel}
          </div>
        </div>
      ) : null}

      {importGuideOpen ? (
        <SkillImportGuide
          onClose={() => setImportGuideOpen(false)}
          onImport={(file) => void skills.importFile(file)}
          importing={skills.busyName === '__import__'}
          notice={skills.notice}
          onDraft={skills.draft}
          onUseDraft={(draft) => void skills.importDraft(draft)}
          drafting={skills.drafting}
          draftError={skills.draftError}
        />
      ) : null}

      <AuditDrawer
        audit={state.audit}
        onClose={controller.closeAudit}
        onRetry={() => void controller.openAudit()}
      />

      {/* 空状态里的「上传素材」入口复用同一个上传方法 */}
      <input
        ref={uploadInputRef}
        type="file"
        accept={UPLOAD_ACCEPT}
        multiple
        className="hidden"
        onChange={onUploadInput}
      />
    </div>
  );
}
