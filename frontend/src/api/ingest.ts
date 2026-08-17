import { api } from './client';
import type { AttachDocumentResult } from './types';

export function ingestFile(agentId: string, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  return api.postForm<AttachDocumentResult>('/ingest/file', formData, { agent_id: agentId });
}
