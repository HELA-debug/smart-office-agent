/** 产物 feature：产物中心页、产物卡片与产物/上传接口。 */
export { ArtifactsPage } from './ArtifactsPage';
export { ArtifactCard } from './ArtifactCard';
export { artifactTypeStyle, stripExtension } from './type-style';
export { ArtifactActions } from './components/ArtifactActions';
export { ArtifactPreviewModal } from './components/ArtifactPreviewModal';
export {
  artifactsApi,
  ACCEPTED_UPLOAD_EXTENSIONS,
  MAX_UPLOAD_BYTES,
  MAX_MEDIA_BYTES,
  maxUploadBytesForFile,
  ARTIFACT_TYPES,
  ARTIFACT_TYPE_LABELS,
  artifactTypeTone,
  uploadTypeLabel,
} from './api';
export type { ArtifactListQuery, ArtifactListData, UploadResult, ThreadFileListData } from './api';
