// Not an exhaustive Powabase-provided list -- Powabase's /api/agents accepts any
// LiteLLM model id with no fixed enum. These four are what's actually usable on
// this project today: no BYOK provider keys are configured, but AI-on-us covers
// anthropic/google/openai, and each was created and run end-to-end successfully
// (verified live 2026-08-16). Leaving the dropdown at "Default" omits the field
// entirely, so Powabase's own default (gpt-5.4-mini) applies.
export interface ModelOption {
  value: string;
  label: string;
}

export const AVAILABLE_MODELS: ModelOption[] = [
  { value: '', label: 'Default (gpt-5.4-mini)' },
  { value: 'gpt-4o', label: 'GPT-4o (OpenAI)' },
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6 (Anthropic)' },
  { value: 'gemini/gemini-2.5-flash', label: 'Gemini 2.5 Flash (Google)' },
];
