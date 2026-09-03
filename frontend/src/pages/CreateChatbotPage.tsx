import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { createChatbot } from '../api/chatbots';
import { describeError } from '../lib/errors';
import { AVAILABLE_MODELS } from '../lib/models';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './FormPage.module.css';

export function CreateChatbotPage() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [agentName, setAgentName] = useState('');
  const [roleDescription, setRoleDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [model, setModel] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await createChatbot(
        name.trim(),
        agentName.trim(),
        roleDescription.trim(),
        systemPrompt.trim() || undefined,
        model || undefined,
      );
      navigate(`/chatbots/${result.chatbot.id}`, { replace: true });
    } catch (err) {
      setError(describeError(err));
      setSubmitting(false);
    }
  }

  const canSubmit = name.trim() && agentName.trim() && roleDescription.trim();

  return (
    <div className={styles.page}>
      <h1>Create a chatbot</h1>
      <form className={styles.form} onSubmit={handleSubmit}>
        {error && <ErrorBanner message={error} />}
        <div className="field">
          <label htmlFor="chatbot-name">Chatbot name</label>
          <input
            id="chatbot-name"
            className="input"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="chatbot-agent-name">First agent's name</label>
          <input
            id="chatbot-agent-name"
            className="input"
            required
            value={agentName}
            onChange={(e) => setAgentName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="chatbot-role">Role description</label>
          <textarea
            id="chatbot-role"
            className="input"
            rows={3}
            required
            placeholder="What this agent handles, so the orchestrator knows when to route to it."
            value={roleDescription}
            onChange={(e) => setRoleDescription(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="chatbot-prompt">System prompt (optional)</label>
          <textarea
            id="chatbot-prompt"
            className="input"
            rows={4}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="chatbot-model">First agent's model (optional)</label>
          <select id="chatbot-model" className="input" value={model} onChange={(e) => setModel(e.target.value)}>
            {AVAILABLE_MODELS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
        <button className="btn btn-primary" type="submit" disabled={submitting || !canSubmit}>
          {submitting ? 'Creating…' : 'Create chatbot'}
        </button>
      </form>
    </div>
  );
}
