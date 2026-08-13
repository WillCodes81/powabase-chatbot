import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { createAgent } from '../api/agents';
import { describeError } from '../lib/errors';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './FormPage.module.css';

export function CreateAgentPage() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const agent = await createAgent(name.trim(), systemPrompt.trim() || undefined);
      navigate(`/agents/${agent.agent_id}`, { replace: true });
    } catch (err) {
      setError(describeError(err));
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.page}>
      <h1>Create an agent</h1>
      <form className={styles.form} onSubmit={handleSubmit}>
        {error && <ErrorBanner message={error} />}
        <div className="field">
          <label htmlFor="agent-name">Name</label>
          <input
            id="agent-name"
            className="input"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="agent-prompt">System prompt (optional)</label>
          <textarea
            id="agent-prompt"
            className="input"
            rows={4}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
        </div>
        <button className="btn btn-primary" type="submit" disabled={submitting || !name.trim()}>
          {submitting ? 'Creating…' : 'Create agent'}
        </button>
      </form>
    </div>
  );
}
