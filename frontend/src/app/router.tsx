import { Navigate, Route, Routes } from 'react-router-dom';
import { ArtifactsPage } from '../features/artifacts';
import { AuditPage } from '../features/audit';
import { KnowledgePage } from '../features/knowledge';
import { ProjectPage } from '../features/projects';
import { SettingsPage } from '../features/settings';
import { SkillsPage } from '../features/skills';
import { WorkbenchPage } from '../features/workbench';
/** 路由表：工作台 + 产物/审计/设置/技能 + 项目页 + 独立知识库检索页。 */
export function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<WorkbenchPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/artifacts" element={<ArtifactsPage />} />
      <Route path="/audit" element={<AuditPage />} />
      <Route path="/skills" element={<SkillsPage />} />
      <Route path="/projects/:projectId" element={<ProjectPage />} />
      <Route path="/knowledge" element={<KnowledgePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
